"""F1: reproducible My Challenge Current scenario with the documented CLI commands:
dev-open, the signed-in participant's own test entry, entries for every development
participant, lock after the real deadline, synthetic results, settle (as of), then
finalise (as of). Run ``settle``, check the browser, then run ``finalise``.

    uv run python tools/e2e_6c5/f1_current_steps.py settle|finalise
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from f1_env import load_accounts, load_env, sql  # noqa: E402
from pty_cli import run_cli  # noqa: E402

ENV, ACC = load_env(), load_accounts()
OWN, ME = ACC["f1own"], ACC["f1me"]
CODE = "dev-f1-current"


def show(args, rc, out, secret="", lines=3):
    print("$ diski9", " ".join(args), "->", rc)
    text = out.replace(secret, "***") if secret else out
    print("\n".join(text.splitlines()[-lines:]))
    assert rc == 0, text


def op(*args):
    rc, out = run_cli([*args, "--operator", OWN["email"]], ENV, password=OWN["password"],
                      timeout=600)  # fmt: skip
    show(args, rc, out, OWN["password"])
    return out


def plain(*args):
    rc, out = run_cli(list(args), ENV, timeout=600)
    show(args, rc, out, lines=2)
    return out


def settle():
    plain("round", "dev-open", "--by-email", OWN["email"], "--deadline-minutes", "1",
          "--spacing-minutes", "1", "--fixtures", "40", "--code", CODE)  # fmt: skip
    args = ["dev-results", "test-entry", "--round", CODE, "--participant", ME["email"],
            "--variant", "1"]  # fmt: skip
    rc, out = run_cli(args, ENV, password=ME["password"])
    show(args, rc, out, ME["password"])
    op("dev-results", "test-entry", "--round", CODE, "--all-dev-participants")
    left = float(sql(f"SELECT extract(epoch FROM deadline_at - now()) FROM app.rounds "
                     f"WHERE code = '{CODE}'"))  # fmt: skip
    print(f"waiting {left:.0f} s for the real deadline")
    time.sleep(max(0.0, left) + 2)
    plain("round", "lock", "--code", CODE)
    op("dev-results", "set-mode", "--round", CODE, "--mode", "synthetic")
    op("dev-results", "scenario", "--round", CODE, "--name", "all-correct")
    cutoff = sql("SELECT to_char((settle_cutoff_at + interval '1 second') AT TIME ZONE 'UTC', "
                 "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') FROM app.rounds "
                 f"WHERE code = '{CODE}'")  # fmt: skip
    op("settle", "run", "--round", CODE, "--as-of", cutoff)


def finalise():
    out = op("round", "finalise-check", "--code", CODE)
    match = re.search(r"--as-of ([^\s)]+)", out)
    assert match, out
    op("round", "finalise", "--code", CODE, "--as-of", match.group(1))


if __name__ == "__main__":
    {"settle": settle, "finalise": finalise}[sys.argv[1]]()
