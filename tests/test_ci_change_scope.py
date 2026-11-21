"""CI documentation-only detection (``tools/ci/change_scope.py``): strict allowlist,
fail-safe defaults, full change sets, and a guard that every ``docs/`` path the
application or the tests read is excluded from the documentation-only scope."""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("change_scope", ROOT / "tools/ci/change_scope.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


@pytest.mark.parametrize(
    "paths",
    [
        ["docs/architecture/phase6c6_implementation.md"],
        ["docs/product/weekly_challenge_decisions.md", "docs/product/weekly_challenge_phase6c_plan.md"],
        ["README.md", "CHANGELOG.md"],
        ["docs/screenshots/phase6c5/f2/j1_desktop.png"],
        ["docs/benchmarks/phase6c5_f4/publication.json", "docs/backend.md"],
    ],
)  # fmt: skip
def test_documentation_only_changes(paths):
    assert cs.classify(paths)[0] == "docs"


@pytest.mark.parametrize(
    "paths",
    [
        [],  # nothing detected: ambiguous
        ["src/diski9/cli.py"],
        ["tests/backend/test_backend_s07_remediation.py"],
        ["tools/e2e_6c5/README.md"],  # Markdown inside a code directory
        ["src/diski9/README.md"],
        [".github/workflows/ci.yml"],
        ["migrations_app/versions/app_0008_x.py"],
        ["pyproject.toml"],
        ["uv.lock"],
        ["package.json"],  # browser-test tooling
        ["package-lock.json"],
        [".env.example"],
        ["docs/legal/terms-beta-2026-11.md"],  # read by the web app
        ["docs/research/weekly_challenge_risk/pool_weekend.json"],  # test and app data
        ["docs/methodology.md"],  # asserted by a test
        ["docs/data.json"],  # non-Markdown outside the artefact folders
        ["docs/backend.md", "src/diski9/backend/db/engine.py"],  # mixed
        ["../outside.md"],
        ["/abs/path.md"],
    ],
)  # fmt: skip
def test_anything_else_runs_the_full_suite(paths):
    assert cs.classify(paths)[0] == "full"


def test_fail_safe_events_and_git_errors():
    assert cs.decide("workflow_dispatch")[0] == "full"
    assert cs.decide("")[0] == "full"
    assert cs.decide("push", before=cs.ZERO, after="a" * 40)[0] == "full"  # new branch
    assert cs.decide("push", before="", after="a" * 40)[0] == "full"
    assert cs.decide("push", before="b" * 40, after="c" * 40)[0] == "full"  # unknown commits
    assert cs.decide("push", before="not-a-sha", after="HEAD")[0] == "full"
    assert cs.decide("pull_request", base="", head="")[0] == "full"


def _has(commit: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT,
                          capture_output=True).returncode == 0  # fmt: skip


@pytest.mark.skipif(not _has("630e021") or not _has("6d7d395"), reason="needs full history")
def test_real_history_full_change_sets():
    # 630e021 changed documentation only; 670283d changed source and tests
    assert cs.decide("push", before="f0ac3c2", after="630e021")[0] == "docs"
    assert cs.decide("push", before="6d7d395", after="670283d")[0] == "full"
    # a push of several commits is judged on all of them (docs, then code)
    assert cs.decide("push", before="c2583c3", after="0570220")[0] == "full"
    # a pull request is judged on everything since the merge base, not the last commit
    assert cs.decide("pull_request", base="c2583c3", head="630e021")[0] == "full"
    # and the git diff itself is what decides (not the fail-safe): these ranges exist
    assert cs.changed_files("f0ac3c2", "630e021", merge_base=False)
    assert cs.changed_files("c2583c3", "630e021", merge_base=True)


def test_every_docs_path_read_by_code_is_excluded():
    """Guard: string literals in src/ and tests/ that open a ``docs/`` path must name
    paths the documentation-only scope excludes (otherwise a docs-only change could
    skip tests that depend on it)."""
    lit = re.compile(r"""["']docs/([^"']+)["']""")
    seg = re.compile(r"""["']docs["']\s*\)?\s*/\s*["']([^"'/]+)["']""")
    found = set()
    for base in ("src", "tests"):
        for f in (ROOT / base).rglob("*.py"):
            if f.resolve() == Path(__file__).resolve():
                continue  # this file's example paths are inputs, not reads
            text = f.read_text(encoding="utf-8")
            found |= {f"docs/{m}" for m in lit.findall(text)}
            found |= {f"docs/{m}/" for m in seg.findall(text)}
    assert found, "the scan should find the known documentation reads"
    for path in sorted(found):
        probe = path + "x.md" if path.endswith("/") else path
        assert not cs.is_doc(probe), f"{path} is read by code but counted as documentation"


def test_link_check(tmp_path):
    (tmp_path / "ok.md").write_text("see [other](other.md) and [web](https://example.com)")
    (tmp_path / "other.md").write_text("x")
    (tmp_path / "bad.md").write_text("see [missing](nowhere.md#part)")
    assert cs.broken_links([str(tmp_path / "ok.md")]) == []
    assert cs.broken_links([str(tmp_path / "bad.md")]) == [f"{tmp_path / 'bad.md'}: nowhere.md"]
