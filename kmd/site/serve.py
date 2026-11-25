"""Serve courses, video byte ranges and the local question-answering endpoint."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re

from ..config import RUNS
from .rag import RagError, ask


class CourseHandler(SimpleHTTPRequestHandler):
    def _send_json(self, status, value):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != "/api/rag/ask":
            self._send_json(404, {"error": "Адрес не найден."})
            return
        port = self.server.server_port
        local_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in local_hosts or (
            origin and origin not in {f"http://{host}" for host in local_hosts}
        ):
            self._send_json(403, {"error": "Откройте урок на локальном сервере курса."})
            return
        if self.headers.get_content_type() != "application/json":
            self._send_json(415, {"error": "Ожидается запрос в формате JSON."})
            return
        length = self.headers.get("Content-Length", "")
        if not re.fullmatch(r"[0-9]{1,5}", length) or not 0 < int(length) <= 16384:
            self._send_json(413, {"error": "Запрос превышает допустимый размер или пуст."})
            return
        try:
            data = json.loads(self.rfile.read(int(length)))
            if not isinstance(data, dict) or not all(
                isinstance(data.get(key), str) for key in ("chapter", "node", "question")
            ):
                raise ValueError
        except ValueError:
            self._send_json(400, {"error": "Проверьте главу, урок и текст вопроса."})
            return
        try:
            answer = ask(data["chapter"], data["node"], data["question"], data.get("history"))
        except RagError as exc:
            self._send_json(exc.status, {"error": str(exc)})
        except (OSError, ValueError, KeyError, TypeError):
            self._send_json(500, {"error": "Не удалось прочитать материалы главы."})
        else:
            self._send_json(200, answer)

    def send_head(self):
        self.bytes_remaining = None
        header = self.headers.get("Range")
        path = Path(self.translate_path(self.path))
        if not header or path.suffix.lower() != ".mp4" or not path.is_file():
            return super().send_head()

        match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", header)
        if not match or not any(match.groups()):
            return super().send_head()
        try:
            media = path.open("rb")
        except OSError:
            return super().send_head()
        length = media.seek(0, 2)
        first, last = match.groups()
        start = int(first) if first else max(0, length - int(last))
        end = min(int(last), length - 1) if first and last else length - 1
        if not 0 <= start <= end:
            media.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{length}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        media.seek(start)
        self.bytes_remaining = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{length}")
        self.send_header("Content-Length", str(self.bytes_remaining))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return media

    def copyfile(self, source, outputfile):
        if self.bytes_remaining is None:
            return super().copyfile(source, outputfile)
        while self.bytes_remaining:
            chunk = source.read(min(65536, self.bytes_remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            self.bytes_remaining -= len(chunk)


def serve(port: int) -> int:
    with ThreadingHTTPServer(("127.0.0.1", port), partial(CourseHandler, directory=RUNS)) as server:
        print(f"Open http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
