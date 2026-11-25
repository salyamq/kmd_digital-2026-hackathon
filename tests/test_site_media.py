from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

from kmd.site.build import lesson_transcript
from kmd.site.serve import CourseHandler


def test_transcript_supports_both_renderers_and_links_known_claims():
    step = {"sources": [{"claim_id": "claim", "page": 12}]}
    passport = {"script": [
        {"start": 1.5, "text": "From the legacy renderer", "claim_ids": ["claim", "orphan"]},
        {"t0": 63, "text": "From vidpipe", "sources": [{"claim_id": "claim"}, {"claim_id": "claim"}]},
    ]}
    cues = lesson_transcript(passport, step)
    assert [cue["clock"] for cue in cues] == ["0:01", "1:03"]
    assert all(cue["sources"] == [{"id": "claim", "page": 12}] for cue in cues)


def test_local_server_supports_video_seeking(tmp_path):
    (tmp_path / "video.mp4").write_bytes(b"0123456789")
    with ThreadingHTTPServer(("127.0.0.1", 0), partial(CourseHandler, directory=tmp_path)) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        conn = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            for header, status, content_range, body in [
                ("bytes=2-4", 206, "bytes 2-4/10", b"234"),
                ("bytes=6-", 206, "bytes 6-9/10", b"6789"),
                ("bytes=-2", 206, "bytes 8-9/10", b"89"),
                ("bytes=12-", 416, "bytes */10", b""),
            ]:
                conn.request("GET", "/video.mp4", headers={"Range": header})
                response = conn.getresponse()
                assert (response.status, response.getheader("Content-Range"), response.read()) == (status, content_range, body)
        finally:
            conn.close()
            server.shutdown()
            thread.join()
