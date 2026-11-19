"""Minimal SMTP capture server for local and CI authentication tests.

Accepts every message and writes it as ``<n>.eml`` into a directory. No relaying,
no authentication, no TLS: bind it to 127.0.0.1 only. Supabase Auth (or any
SMTP client) sends verification and recovery emails here so tests can read the
token links. Development and testing only.
"""

from __future__ import annotations

import argparse
import socketserver
import threading
from pathlib import Path


class _Handler(socketserver.StreamRequestHandler):
    def _send(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())

    def handle(self) -> None:
        self._send("220 diski9-mail-sink ESMTP")
        data_mode, lines = False, []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if data_mode:
                if line == ".":
                    data_mode = False
                    self.server.store("\n".join(lines))  # type: ignore[attr-defined]
                    lines = []
                    self._send("250 OK: queued")
                else:
                    lines.append(line[1:] if line.startswith("..") else line)
                continue
            cmd = line.split(" ", 1)[0].upper()
            if cmd in ("EHLO", "HELO"):
                self._send("250-diski9-mail-sink")
                self._send("250 SIZE 10485760")
            elif cmd in ("MAIL", "RCPT", "RSET", "NOOP"):
                self._send("250 OK")
            elif cmd == "DATA":
                data_mode = True
                self._send("354 End data with <CR><LF>.<CR><LF>")
            elif cmd == "QUIT":
                self._send("221 Bye")
                return
            else:
                self._send("502 Command not implemented")


class MailSink(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host: str, port: int, outdir: Path):
        super().__init__((host, port), _Handler)
        self.outdir = outdir
        self.outdir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def store(self, message: str) -> None:
        with self._lock:
            n = len(list(self.outdir.glob("*.eml"))) + 1
            (self.outdir / f"{n:05d}.eml").write_text(message, encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2500)
    p.add_argument("--dir", default="tmp/mail")
    a = p.parse_args()
    if a.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("bind the mail sink to localhost only")
    with MailSink(a.host, a.port, Path(a.dir)) as srv:
        srv.serve_forever()


if __name__ == "__main__":
    main()
