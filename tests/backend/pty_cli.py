"""Drive the real ``diski9`` CLI through a pseudo-terminal (no mocks).

The operator commands read passwords with ``getpass`` from a real terminal only,
so tests run them exactly as a person would: a child process attached to a pty,
answering the prompts it prints. The transcript is everything the terminal showed
(``getpass`` disables echo, so a typed password must never appear in it).
"""

from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Session:
    def __init__(self, args: list[str], env: dict[str, str], *, stdin_tty: bool = True):
        self.master, slave = pty.openpty()
        full_env = {k: v for k, v in os.environ.items() if not k.startswith("DISKI9_")}
        full_env.update(env)
        full_env["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "diski9.cli", *args],
            stdin=slave if stdin_tty else subprocess.PIPE,
            stdout=slave,
            stderr=slave,
            env=full_env,
            cwd=ROOT,
            close_fds=True,
        )
        os.close(slave)
        self.buffer = ""

    def _read(self, timeout: float) -> bool:
        ready, _, _ = select.select([self.master], [], [], timeout)
        if not ready:
            return False
        try:
            chunk = os.read(self.master, 65536)
        except OSError:
            return False
        if not chunk:
            return False
        self.buffer += chunk.decode(errors="replace")
        return True

    def expect(self, pattern: str, timeout: float = 60.0) -> str:
        deadline = time.monotonic() + timeout
        rx = re.compile(pattern)
        while time.monotonic() < deadline:
            if rx.search(self.buffer):
                return self.buffer
            if not self._read(0.2) and self.proc.poll() is not None:
                while self._read(0.05):
                    pass
                if rx.search(self.buffer):
                    return self.buffer
                break
        raise AssertionError(f"did not see {pattern!r}; transcript:\n{self.buffer}")

    def send(self, text: str) -> None:
        os.write(self.master, (text + "\n").encode())

    def finish(self, timeout: float = 120.0) -> tuple[int, str]:
        deadline = time.monotonic() + timeout
        while self.proc.poll() is None and time.monotonic() < deadline:
            self._read(0.2)
        while self._read(0.05):
            pass
        if self.proc.poll() is None:
            self.proc.kill()
            raise AssertionError(f"CLI did not finish; transcript:\n{self.buffer}")
        os.close(self.master)
        return self.proc.returncode, self.buffer


def run_cli(
    args: list[str],
    env: dict[str, str],
    *,
    password: str | None = None,
    answers: list[tuple[str, str]] = (),
    timeout: float = 120.0,
) -> tuple[int, str]:
    """Run one command; answer the password prompt (if ``password``) and then each
    ``(prompt regex, answer)`` in order. Returns ``(exit code, transcript)``."""
    s = Session(args, env)
    if password is not None:
        s.expect(r"password for .*: ", timeout)
        s.send(password)
    for prompt, answer in answers:
        s.expect(prompt, timeout)
        s.send(answer)
    return s.finish(timeout)
