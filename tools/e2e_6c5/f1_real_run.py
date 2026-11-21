"""F1: the real ten-round development championship through the CLI (pseudo-terminal,
password typed at the hidden prompt, local Supabase Auth, default 60 s deadlines). It
sends SIGINT (what Ctrl-C delivers) while round 9 waits for its deadline, then runs
the same command again to resume.

    uv run python tools/e2e_6c5/f1_real_run.py
"""

import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from f1_env import load_accounts, load_env  # noqa: E402
from pty_cli import Session, run_cli  # noqa: E402

ENV, ACC = load_env(), load_accounts()
PW = ACC["f1own"]["password"]
ARGS = ["dev-championship", "run", "--preset", "ten-round-complete", "--run-id", "real10",
        "--operator", ACC["f1own"]["email"]]  # fmt: skip

start = time.time()
s = Session(ARGS, ENV)
s.expect(r"password for .*: ", 60)
s.send(PW)
s.expect(r"waiting for the dev-real10-\w+-r09 deadline", 1800)
os.kill(s.proc.pid, signal.SIGINT)  # Ctrl-C once: stop at the next safe point
rc, out = s.finish(300)
print("=== first run (SIGINT during round 9) ===")
print(out.replace(PW, "***"))
print(f"exit {rc} after {time.time() - start:.0f} s")
rc, out = run_cli(ARGS, ENV, password=PW, timeout=3000)
print("=== resumed with the same command ===")
print(out.replace(PW, "***"))
print(f"exit {rc} after {time.time() - start:.0f} s in total")
