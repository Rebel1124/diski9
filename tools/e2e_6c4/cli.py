"""Run one ``diski9`` operator command in a pseudo-terminal for the Phase 6C.4
browser journeys (local development only).

The command asks for the account's password exactly as it does for a person; this
helper types it at the hidden prompt. Throw-away local accounts and their
passwords live in ``tmp/e2e_6c4/accounts.json`` (git-ignored), never in the
repository, arguments or logs. Usage::

    uv run python tools/e2e_6c4/cli.py ROLE [--confirm CODE] -- results show --round dev-x

ROLE is a key of accounts.json (for example ``operator``, ``owner``, ``pat``).
The account's email is added as ``--operator`` (or ``--participant`` for
``dev-results test-entry``). Prints the transcript and exits with the command's code.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "backend"))

from pty_cli import run_cli  # noqa: E402


def main() -> int:
    argv = sys.argv[1:]
    role = argv.pop(0)
    confirm = None
    if argv and argv[0] == "--confirm":
        confirm = argv[1]
        argv = argv[2:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    accounts = json.loads((ROOT / "tmp" / "e2e_6c4" / "accounts.json").read_text())
    acct = accounts[role]
    flag = "--participant" if argv[:2] == ["dev-results", "test-entry"] else "--operator"
    env = {k: v for k, v in os.environ.items() if k.startswith("DISKI9_")}
    answers = [(r"Type the round code", confirm)] if confirm else []
    rc, out = run_cli([*argv, flag, acct["email"]], env, password=acct["password"],
                      answers=answers)  # fmt: skip
    print(out.replace(acct["password"], "<password>"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
