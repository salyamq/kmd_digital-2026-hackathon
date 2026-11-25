"""Serve the offline courses locally with HTTP byte ranges for video seeking."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re

from ..config import RUNS


class CourseHandler(SimpleHTTPRequestHandler):
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
