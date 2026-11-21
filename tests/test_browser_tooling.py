"""Browser-test tooling guard. The browser tests skip themselves when Node or the
Node ``playwright`` package is missing (convenient on a developer machine). GitHub CI
sets ``DISKI9_REQUIRE_BROWSER=1`` so that missing or broken tooling fails the run
instead of silently skipping those tests (Phase 6C.6 Stage B, owner-approved)."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

REQUIRE = os.environ.get("DISKI9_REQUIRE_BROWSER") == "1"

LAUNCH = """
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.setContent('<p id="x">ok</p>');
  console.log(await p.textContent('#x'));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_browser_tooling_available_and_launches():
    node = shutil.which("node")
    if node is None:
        if REQUIRE:
            pytest.fail("DISKI9_REQUIRE_BROWSER=1 but node is not installed")
        pytest.skip("node not available")
    probe = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, text=True)
    if probe.returncode:
        if REQUIRE:
            pytest.fail(
                f"DISKI9_REQUIRE_BROWSER=1 but playwright cannot be loaded:\n{probe.stderr}"
            )
        pytest.skip("playwright for node not available")
    run = subprocess.run([node, "-e", LAUNCH], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr  # installed but Chromium cannot start: a failure
    assert run.stdout.strip().splitlines()[-1] == "ok"
