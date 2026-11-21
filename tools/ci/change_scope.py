"""Decide whether a CI run may skip the test suite because only documentation
changed (owner-approved CI work item, Phase 6C.6 Stage B). Standard library only.

    python3 tools/ci/change_scope.py --event push --before SHA --after SHA
    python3 tools/ci/change_scope.py --event pull_request --base SHA --head SHA
    python3 tools/ci/change_scope.py --check-links FILE.md [...]

Prints ``scope=docs`` or ``scope=full`` (and appends it to ``$GITHUB_OUTPUT`` when
set). **Fail-safe:** anything ambiguous is ``full`` — an unknown event, a new
branch (no previous commit), a failed or empty ``git diff``, or any changed path
outside the allowlist. Mixed documentation and code changes are ``full``.

* **push:** every file changed between the previous tip (``before``) and the new
  tip (``after``), i.e. all commits in the push.
* **pull_request:** every file changed on the branch since it left the base
  (``git diff base...head``, the merge base), not only the latest commit.

Documentation-only means every changed path is:

* a Markdown file (``*.md``) outside ``src/``, ``tests/``, ``tools/``,
  ``migrations*/``, ``.github/`` and ``scripts/``; or
* a screenshot or benchmark artefact under ``docs/screenshots/`` or
  ``docs/benchmarks/``;

and none is in :data:`READ_BY_CODE` — documentation the application or the tests
read (``docs/legal/`` terms pages, ``docs/research/`` data, ``docs/methodology.md``).
``tests/test_ci_change_scope.py`` scans the code for ``docs/`` paths it opens and
fails if one is missing from that list, so a new dependency cannot slip through.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZERO = "0" * 40

CODE_DIRS = ("src/", "tests/", "tools/", ".github/", "scripts/")
ARTEFACT_DIRS = ("docs/screenshots/", "docs/benchmarks/")
# documentation read by the application or by tests: changes need the full suite
READ_BY_CODE = ("docs/legal/", "docs/research/", "docs/methodology.md")


def is_doc(path: str) -> bool:
    """True only for paths whose change cannot affect code or tests."""
    p = path.strip()
    if not p or p.startswith("/") or ".." in Path(p).parts:
        return False
    if any(p == r or p.startswith(r) for r in READ_BY_CODE):
        return False
    if p.startswith(CODE_DIRS) or p.startswith("migrations"):
        return False
    if p.startswith(ARTEFACT_DIRS):
        return True
    return p.endswith(".md")


def classify(paths: list[str]) -> tuple[str, str]:
    """(scope, reason) for a list of changed paths."""
    paths = [p for p in (x.strip() for x in paths) if p]
    if not paths:
        return "full", "no changed files detected"
    code = [p for p in paths if not is_doc(p)]
    if code:
        return "full", f"{len(code)} non-documentation path(s), e.g. {code[0]}"
    return "docs", f"{len(paths)} documentation-only path(s)"


def changed_files(base: str, head: str, *, merge_base: bool) -> list[str] | None:
    """Files changed between ``base`` and ``head``; ``None`` if git cannot tell."""
    if not base or not head or base == ZERO or not re.fullmatch(r"[0-9a-fA-F]{7,40}", base) \
            or not re.fullmatch(r"[0-9a-fA-F]{7,40}", head):  # fmt: skip
        return None
    rng = f"{base}...{head}" if merge_base else f"{base}..{head}"
    try:
        out = subprocess.run(["git", "diff", "--name-only", "--no-renames", rng], cwd=ROOT,
                             capture_output=True, text=True, timeout=60, check=True)  # fmt: skip
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.splitlines()


def decide(event: str, *, before="", after="", base="", head="") -> tuple[str, str]:
    if event == "push":
        files = changed_files(before, after, merge_base=False)
    elif event == "pull_request":
        files = changed_files(base, head, merge_base=True)
    else:
        return "full", f"event {event or '(none)'} always runs the full suite"
    if files is None:
        return "full", "change detection unavailable (new branch or git error)"
    return classify(files)


LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)]*)?\)")


def broken_links(md_files: list[str]) -> list[str]:
    """Relative links in the given Markdown files that point to missing files."""
    bad = []
    for name in md_files:
        f = ROOT / name
        if not f.is_file() or f.suffix != ".md":
            continue
        for target in LINK.findall(f.read_text(encoding="utf-8", errors="replace")):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("/"):
                continue  # external or absolute
            if not (f.parent / target).resolve().exists():
                bad.append(f"{name}: {target}")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--event", default="")
    ap.add_argument("--before", default="")
    ap.add_argument("--after", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--head", default="")
    ap.add_argument("--check-links", nargs="*", metavar="FILE")
    a = ap.parse_args(argv)
    if a.check_links is not None:
        bad = broken_links(a.check_links)
        for b in bad:
            print(f"broken link: {b}")
        print(f"checked {len(a.check_links)} file(s); {len(bad)} broken link(s)")
        return 1 if bad else 0
    try:
        scope, reason = decide(a.event, before=a.before, after=a.after, base=a.base,
                               head=a.head)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - any surprise means the full suite
        scope, reason = "full", f"change detection failed ({type(exc).__name__})"
    print(f"scope={scope}")
    print(f"reason: {reason}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"scope={scope}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
