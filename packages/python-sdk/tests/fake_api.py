"""A fake AgentTrace API for exercising the SDK's upload path.

Standard library only, like the SDK itself: a real HTTP server on a loopback
port proves the transport actually speaks HTTP, which monkeypatching urllib
would not.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Request:
    """One request the fake API received."""

    path: str
    body: Any


@dataclass
class FakeAPI:
    """Live state of a running fake API."""

    status: int = 201
    delay: float = 0.0
    url: str = ""
    requests: list[Request] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def bodies(self) -> list[Any]:
        with self.lock:
            return [r.body for r in self.requests]


class _QuietServer(ThreadingHTTPServer):
    """Silence the traceback a client disconnect would otherwise print.

    The timeout test hangs up mid-response on purpose, which is an error for
    the handler but the expected outcome for the test.
    """

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass


@contextmanager
def fake_api(status: int = 201, delay: float = 0.0) -> Iterator[FakeAPI]:
    """Run a fake ingest endpoint on a loopback port for the duration."""
    state = FakeAPI(status=status, delay=delay)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            with state.lock:
                state.requests.append(Request(path=self.path, body=parsed))

            if state.delay:
                time.sleep(state.delay)

            payload = json.dumps({"detail": "fake"}).encode()
            self.send_response(state.status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            pass

    server = _QuietServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    # A short poll interval so tearing the server down is not the slowest
    # thing in the suite; the default 0.5s would be paid once per test.
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def closed_port() -> int:
    """A port number nothing is listening on, for the API-down tests."""
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
