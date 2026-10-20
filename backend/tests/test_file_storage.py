import hashlib
from io import BytesIO
from uuid import uuid4

import pytest

from app.security.errors import Denied


def test_private_store_is_bounded_non_overwriting_and_rejects_symlinks(tmp_path):
    from app.storage.local import LocalStore

    store = LocalStore(tmp_path / "files", max_bytes=16)
    org, file_id = uuid4(), uuid4()
    with store.stage() as staged:
        staged.write(b"hello")
        assert staged.sha256 == hashlib.sha256(b"hello").hexdigest()
        store.publish(staged, org, file_id)
        with store.open(org, file_id) as body:
            assert body.read() == b"hello"
        with pytest.raises(FileExistsError):
            store.publish(staged, org, file_id)
    with pytest.raises(Denied, match="FILE_TOO_LARGE"), store.stage() as staged:
        staged.write(b"x" * 17)
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    store.object_path(org, file_id).unlink()
    store.object_path(org, file_id).symlink_to(outside)
    with pytest.raises((OSError, Denied)):
        store.open(org, file_id)
    assert not list((tmp_path / "files" / "staging").iterdir())


def test_media_validation_cross_checks_name_mime_and_bytes():
    from pathlib import Path

    from app.storage.validation import validate

    root = Path(__file__).parent / "fixtures" / "files"
    for suffix, media in [
        ("mp4", "video/mp4"),
        ("pdf", "application/pdf"),
        ("png", "image/png"),
        ("jpg", "image/jpeg"),
    ]:
        with (root / ("tiny." + suffix)).open("rb") as fixture:
            assert validate(fixture, "tiny." + suffix, media) == media
    assert validate(BytesIO("中文 script".encode()), "剧本.txt", "text/plain") == "text/plain"
    for name, mime, data in [
        ("x.exe", "text/plain", b"hello"),
        ("../x.txt", "text/plain", b"hello"),
        ("x.txt", "text/plain", b"<html>secret</html>"),
        ("x.txt", "text/plain", b"\x00bad"),
        ("x.mp4", "video/mp4", b"not a video"),
        ("x.pdf", "application/pdf", b"%PDF-1.7 broken"),
        ("x.txt", "image/png", b"hello"),
        ("x.txt", "text/plain", b""),
    ]:
        with pytest.raises(Denied, match="INVALID_FILE"):
            validate(BytesIO(data), name, mime)


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example/a",
        "file:///etc/passwd",
        "https://user:pass@media.example/a",
        "https://127.0.0.1/a",
        "https://media.example:444/a",
        "https://media.example.evil/a",
        "https://media.example/a#fragment",
        "https://media.example/\r\nx",
    ],
)
def test_external_url_rejects_unsafe_syntax_before_dns(url):
    from app.storage.external import resolve_url

    with pytest.raises(Denied, match="UNSAFE_URL"):
        resolve_url(url, ["media.example"], resolver=lambda *args: pytest.fail("DNS must not run"))


def test_external_resolution_rejects_any_private_answer_and_pins_public_ip():
    from app.storage.external import resolve_url

    def resolver(host, port, **kwargs):
        return [(2, 1, 6, "", ("93.184.215.14", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]

    with pytest.raises(Denied, match="UNSAFE_URL"):
        resolve_url("https://media.example/a", ["media.example"], resolver=resolver)
    target = resolve_url(
        "https://media.example/a?x=1",
        ["media.example"],
        resolver=lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))],
    )
    assert target.host == "media.example" and target.ip == "93.184.215.14"
    assert target.path == "/a?x=1"


def test_fetch_checks_redirect_target_and_size_and_preserves_host():
    from app.storage.external import fetch
    from app.storage.local import Staged

    calls = []

    class Response(BytesIO):
        status = 302

        def getheader(self, key, default=None):
            return {"Location": "https://127.0.0.1/private"}.get(key, default)

    class Connection:
        sock = None

        def __init__(self, target, timeout):
            calls.append(target)

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    resolver = lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))]
    with pytest.raises(Denied, match="UNSAFE_URL"):
        fetch(
            "https://media.example/a",
            ["media.example"],
            Staged(BytesIO(), "test", 16),
            resolver=resolver,
            connector=Connection,
        )
    assert len(calls) == 1 and calls[0].ip == "93.184.215.14" and calls[0].host == "media.example"

    class Body(Response):
        status = 200

        def getheader(self, key, default=None):
            return {"Content-Length": "17", "Content-Type": "text/plain"}.get(key, default)

    class Large(Connection):
        def getresponse(self):
            return Body(b"x" * 17)

    with pytest.raises(Denied, match="FILE_TOO_LARGE"):
        fetch(
            "https://media.example/a",
            ["media.example"],
            Staged(BytesIO(), "test", 16),
            resolver=resolver,
            connector=Large,
        )


def test_fetch_consumes_bounded_single_reads_not_unbounded_fill_loop():
    from app.storage.external import fetch
    from app.storage.local import Staged

    class Body(BytesIO):
        status = 200

        def getheader(self, key, default=None):
            return {"Content-Length": "5", "Content-Type": "text/plain"}.get(key, default)

        def read(self, *args):
            raise AssertionError("read(n) may keep filling forever under slow trickle")

    class Connection:
        sock = None

        def __init__(self, *args):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Body(b"hello")

        def close(self):
            pass

    staged = Staged(BytesIO(), "test", 16)
    media, _ = fetch(
        "https://media.example/a",
        ["media.example"],
        staged,
        resolver=lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))],
        connector=Connection,
    )
    assert media == "text/plain" and staged.size == 5


def test_stale_stage_cleanup_ignores_live_new_and_journal_referenced_files(tmp_path):
    import os
    import time

    from app.storage.local import LocalStore

    store = LocalStore(tmp_path / "files")
    try:
        with store.stage() as staged:
            active = store.root / "staging" / staged.name
            os.utime(active, (time.time() - 7200,) * 2)
            old = store.root / "staging" / (uuid4().hex + ".part")
            old.write_bytes(b"partial")
            protected = store.root / "staging" / (uuid4().hex + ".part")
            protected.write_bytes(b"needed")
            recent = store.root / "staging" / (uuid4().hex + ".part")
            recent.write_bytes(b"recent")
            for path in (old, protected):
                os.utime(path, (time.time() - 7200,) * 2)
            assert store.cleanup_staging(exclude={protected.name}) == 1
            assert active.exists() and protected.exists() and recent.exists() and not old.exists()
    finally:
        store.close()


def test_store_refuses_existing_world_readable_private_directory(tmp_path):
    import os

    from app.storage.local import LocalStore

    root = tmp_path / "files"
    root.mkdir()
    os.chmod(root, 0o755)
    with pytest.raises(Denied, match="SERVICE_NOT_READY"):
        LocalStore(root)


def test_text_allows_standard_page_breaks_without_allowing_binary_controls():
    from app.storage.validation import validate

    assert validate(BytesIO(b"page one\n\fpage two\n"), "pages.txt", "text/plain") == "text/plain"
    with pytest.raises(Denied, match="INVALID_FILE"):
        validate(BytesIO(b"still\x00binary"), "bad.txt", "text/plain")


def test_connection_close_slow_chunk_framing_is_aborted_by_total_deadline():
    import http.client
    import socket
    import threading
    import time

    from app.storage.external import fetch
    from app.storage.local import Staged

    client_socket, server_socket = socket.socketpair()
    stopped = threading.Event()

    def server():
        try:
            conn = server_socket
            with conn:
                conn.settimeout(2)
                request = b""
                while b"\r\n\r\n" not in request:
                    request += conn.recv(4096)
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n1;"
                )
                for _ in range(100):
                    if stopped.wait(0.02):
                        break
                    conn.sendall(b"a")
                conn.sendall(b"\r\nZ\r\n0\r\n\r\n")
        except OSError:
            pass
        finally:
            server_socket.close()

    worker = threading.Thread(target=server, daemon=True)
    worker.start()

    class LocalConnection(http.client.HTTPConnection):
        def __init__(self, target, timeout):
            super().__init__("media.example", timeout=timeout)
            self.transport = None

        def connect(self):
            self.sock = client_socket
            self.sock.settimeout(self.timeout)
            self.transport = self.sock.dup()

        def abort(self):
            if self.transport:
                try:
                    self.transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        def release(self):
            self.close()
            if self.transport:
                self.transport.close()

    start = time.monotonic()
    try:
        with pytest.raises(Denied, match="FETCH_FAILED"):
            fetch(
                "https://media.example/a",
                ["media.example"],
                Staged(BytesIO(), "test", 16),
                resolver=lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))],
                connector=LocalConnection,
                total_timeout=0.2,
            )
        assert time.monotonic() - start < 1
    finally:
        stopped.set()
        worker.join(timeout=3)
        client_socket.close()
        server_socket.close()


def test_fetch_rejects_huge_content_length_without_integer_parser_error():
    from app.storage.external import fetch
    from app.storage.local import Staged

    class Body(BytesIO):
        status = 200

        def getheader(self, key, default=None):
            return "9" * 5000 if key == "Content-Length" else default

    class Connection:
        sock = None

        def __init__(self, *args):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Body()

        def close(self):
            pass

    with pytest.raises(Denied, match="FILE_TOO_LARGE"):
        fetch(
            "https://media.example/a",
            ["media.example"],
            Staged(BytesIO(), "test", 16),
            resolver=lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))],
            connector=Connection,
        )
