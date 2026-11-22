"""Stage F3 O-6: the B2 Governance configuration script, run against a fake `b2`.

The fake mimics B2 CLI 5.x output shapes (read from its source), including the fact that
`b2 account authorize` prints the application key and auth token on success."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "f3" / "owner" / "f3-b2-configure-governance.sh"
BUCKET = "diski9-f3-0a1b2c3d"
SECRET = "FAKE0MASTER0KEY0NOT0REAL0001"  # fake values only
ALPHA_SECRET = "fakeAlphabeticOnlySecretValueNotReal"  # no digits: defeats digit-based scrubbing
TOKEN = "FAKE0AUTH0TOKEN0NOT0REAL0002"
ACCOUNT = "FAKEACCOUNT01"
LIFECYCLE = [
    {"daysFromHidingToDeleting": 30, "daysFromUploadingToHiding": 14, "fileNamePrefix": "diski9/daily/"},
    {"daysFromHidingToDeleting": 30, "daysFromUploadingToHiding": 56, "fileNamePrefix": "diski9/weekly/"},
    {"daysFromHidingToDeleting": 30, "daysFromUploadingToHiding": 1, "fileNamePrefix": "diski9/canary/"},
]  # fmt: skip

FAKE = r"""#!/usr/bin/env python3
import json, os, sys, time
state_path = os.environ["FAKE_B2_STATE"]
st = json.load(open(state_path))
log = open(os.environ["FAKE_B2_LOG"], "a")
log.write(json.dumps({"argv": sys.argv[1:], "info": os.environ.get("B2_ACCOUNT_INFO"),
                      "env_key": os.environ.get("B2_APPLICATION_KEY")}) + "\n")
a = sys.argv[1:]
def save(): json.dump(st, open(state_path, "w"))
def out(o): print(json.dumps(o, indent=2))
if a[:1] == ["version"]:
    print("b2 command line tool, version 5.0.3 (b2sdk version 2.13.5)")
elif a[:2] == ["account", "authorize"]:
    open(os.environ["B2_ACCOUNT_INFO"], "w").write(st["secret"])  # b2 caches the key
    if st.get("authorize_fail"):
        sys.stderr.write("ERROR: unable to authorize account: key " + st["secret"] + "\n"); sys.exit(1)
    out({"accountId": st["account"], "applicationKey": st["secret"], "accountAuthToken": st["token"]})
elif a[:2] == ["account", "clear"]:
    p = os.environ.get("B2_ACCOUNT_INFO")
    if p and os.path.exists(p): os.remove(p)
elif a[:2] == ["bucket", "get"]:
    if st.get("get_garbage"):
        print("<html>unexpected</html> token=" + st["token"]); sys.exit(0)
    out(dict(st["bucket"], bucketName=a[2], accountId=st["account"], bucketId="bkt1"))
elif a[:2] == ["bucket", "update"] and st.get("update_fail"):
    sys.stderr.write("ERROR: b2 failed, Authorization: " + st["token"] + " account " + st["account"]
                     + " key " + st["alpha"] + "\n")
    print("raw response " + st["alpha"])
    sys.exit(1)
elif a[:2] == ["bucket", "update"]:
    m = a[a.index("--default-retention-mode") + 1]
    d, u = a[a.index("--default-retention-period") + 1].split()
    if st.get("update_noop"): pass
    else: st["bucket"]["defaultRetention"] = {"mode": m, "period": {"duration": int(d), "unit": u}}
    save(); out(st["bucket"])
elif a[:2] == ["file", "upload"]:
    now = int(time.time() * 1000)
    r = st["bucket"]["defaultRetention"]
    mode = st.get("force_file_mode", r["mode"])
    st["file"] = {"fileId": "4_zfile1", "fileName": a[-1], "uploadTimestamp": now,
                  "fileRetention": {"mode": mode, "retainUntilTimestamp":
                  now + st.get("lock_days", 30) * 86400000}, "legalHold": st.get("legal_hold"),
                  "action": "upload"}
    save()
    # exactly what B2 CLI 5.0.3 prints (console_tool.py, file upload _run)
    url_id = st.get("url_file_id", st["file"]["fileId"])
    if not st.get("no_url_lines"):
        print("URL by file name: https://f003.backblazeb2.com/file/" + a[-3] + "/" + a[-1])
        print("URL by fileId: https://f003.backblazeb2.com/b2api/v3/b2_download_file_by_id?fileId=" + url_id)
    if st.get("upload_garbage"):
        print("not json at all")
    else:
        out(st["file"])
elif a[:2] == ["file", "info"]:
    files = {f["fileId"]: f for f in st.get("listing", [])}
    if "file" in st: files[st["file"]["fileId"]] = st["file"]
    fid = a[2].split("b2id://", 1)[1]
    out(files[fid])
elif a[:1] == ["ls"]:
    items = st.get("listing", [])
    print("[")  # B2 CLI 5.0.3 --json format: "[", objects joined by ",", "]"
    print(",".join(json.dumps(i, indent=2) for i in items))
    print("]")
elif a[:1] in (["rm"], ["delete-file-version"], ["hide-file"]) or a[:2] in (
        ["file", "hide"], ["file", "update"], ["bucket", "delete"], ["key", "create"]):
    sys.exit("fake b2: forbidden " + " ".join(a))
else:
    sys.exit("fake b2: unsupported " + " ".join(a))
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "b2").write_text(FAKE)
    (bindir / "b2").chmod(0o755)
    state = {"secret": SECRET, "token": TOKEN, "account": ACCOUNT, "alpha": ALPHA_SECRET, "bucket": {"bucketType": "allPrivate", "isFileLockEnabled": True,
             "defaultRetention": {"mode": None}, "lifecycleRules": LIFECYCLE}}  # fmt: skip
    (tmp_path / "state.json").write_text(json.dumps(state))
    e = {k: v for k, v in os.environ.items() if not k.startswith("B2_")}
    e.update(PATH=f"{bindir}:{os.environ['PATH']}", FAKE_B2_STATE=str(tmp_path / "state.json"),
             FAKE_B2_LOG=str(tmp_path / "log.jsonl"), HOME=str(tmp_path))  # fmt: skip
    return e, tmp_path


def _set(tmp_path, **kv):
    p = tmp_path / "state.json"
    st = json.loads(p.read_text())
    for k, v in kv.items():
        if k == "bucket":
            st["bucket"].update(v)
        else:
            st[k] = v
    p.write_text(json.dumps(st))


def _run(env, answers="KEYID123\nGOVERNANCE\n", bucket=BUCKET):
    e, _ = env
    return subprocess.run([str(SCRIPT), bucket], input=answers, env=e, capture_output=True,
                          text=True, timeout=60)  # fmt: skip


def _calls(tmp_path):
    return [json.loads(x) for x in (tmp_path / "log.jsonl").read_text().splitlines()]


def _no_secrets(r):
    text = r.stdout + r.stderr
    for value in (SECRET, TOKEN, ACCOUNT, ALPHA_SECRET, "KEYID123", "bkt1", "4_zfile1"):
        assert value not in text, value


def _shm():
    return {p.name for p in Path("/dev/shm").iterdir()}


def test_happy_path_sets_governance_and_proves_it_on_the_uploaded_version(env):
    e, tmp = env
    before = _shm()
    r = _run(env)
    assert r.returncode == 0, r.stderr
    _no_secrets(r)
    ev = json.loads(r.stdout[r.stdout.index("{") : r.stdout.rindex("}") + 1])
    assert ev["defaultRetention"] == {
        "mode": "governance",
        "period": {"duration": 30, "unit": "days"},
    }
    assert ev["canary"]["retentionMode"] == "governance" and ev["canary"]["lockDays"] == 30.0
    calls = _calls(tmp)
    update = next(c["argv"] for c in calls if c["argv"][:2] == ["bucket", "update"])
    assert update[update.index("--default-retention-mode") + 1] == "governance"
    assert "compliance" not in json.dumps([c["argv"] for c in calls])
    info = next(c["argv"] for c in calls if c["argv"][:2] == ["file", "info"])
    assert info[2] == "b2id://4_zfile1"  # the uploaded version, by file ID
    # the key never reached argv or the environment; the cache lived in RAM and is gone
    assert all(SECRET not in json.dumps(c) and c["env_key"] is None for c in calls)
    assert all(c["info"] and c["info"].startswith("/dev/shm/") for c in calls)
    cache = next(c["info"] for c in calls if c["argv"][:2] == ["account", "authorize"])
    assert cache.startswith("/dev/shm/") and not Path(cache).exists()
    assert ["account", "clear"] in [c["argv"] for c in calls] and _shm() == before
    assert not (tmp / ".b2_account_info").exists()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"bucket": {"isFileLockEnabled": False}}, "Object Lock is NOT enabled"),
        ({"bucket": {"bucketType": "allPublic"}}, "not private"),
        ({"bucket": {"defaultRetention": {"mode": "compliance", "period": {"duration": 1, "unit": "days"}}}},
         "COMPLIANCE (or unknown) default retention"),
        ({"bucket": {"lifecycleRules": LIFECYCLE[:2]}}, "lifecycle rules differ"),
    ],
)  # fmt: skip
def test_refuses_unsafe_starting_states_without_changing_anything(env, change, message):
    _, tmp = env
    _set(tmp, **change)
    r = _run(env)
    assert r.returncode != 0 and message in r.stderr
    argvs = [c["argv"] for c in _calls(tmp)]
    assert not any(a[:2] in (["bucket", "update"], ["file", "upload"]) for a in argvs)
    assert ["account", "clear"] in argvs


def test_nothing_changes_without_typed_confirmation(env):
    _, tmp = env
    r = _run(env, answers="KEYID123\nyes\n")
    assert r.returncode != 0 and "not confirmed" in r.stderr
    assert not any(c["argv"][:2] == ["bucket", "update"] for c in _calls(tmp))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"update_noop": True}, "not governance/30 days after the update"),
        ({"force_file_mode": "none"}, "NOT governance-locked"),
        ({"lock_days": 1}, "does not expire ~30 days"),
        ({"legal_hold": "on"}, "unexpected legal hold"),
        ({"get_garbage": True}, "unreadable bucket record"),
        ({"update_fail": True}, "retention update failed"),
        ({"authorize_fail": True}, "authorisation failed"),
    ],
)
def test_failed_verification_stops_and_still_cleans_up(env, change, message):
    _, tmp = env
    before = _shm()
    _set(tmp, **change)
    r = _run(env)
    assert r.returncode != 0 and message in r.stderr
    calls = _calls(tmp)
    assert calls[-1]["argv"] == ["account", "clear"] and not Path(calls[-1]["info"]).exists()
    assert _shm() == before
    _no_secrets(r)


def test_refuses_keys_in_the_environment_and_bad_bucket_names(env):
    e, tmp = env
    r = subprocess.run([str(SCRIPT), BUCKET], input="", env={**e, "B2_APPLICATION_KEY": "x"},
                       capture_output=True, text=True)  # fmt: skip
    assert r.returncode != 0 and "must not be in the environment" in r.stderr
    r = _run(env, bucket="some-other-bucket")
    assert r.returncode != 0 and "diski9-f3-<8 hex>" in r.stderr
    assert not (tmp / "log.jsonl").exists()  # b2 was never called


def test_b2_errors_are_never_printed_only_a_generic_step_message(env):
    """Raw b2 output never reaches the terminal on failure, even a secret with no digits."""
    _, tmp = env
    _set(tmp, update_fail=True)
    r = _run(env)
    assert r.returncode != 0
    assert "retention update failed (b2 reported an error; its raw message is not shown" in r.stderr
    assert ALPHA_SECRET not in r.stdout + r.stderr and "raw response" not in r.stdout + r.stderr
    assert "Authorization" not in r.stderr and "<redacted>" not in r.stderr
    _no_secrets(r)


@pytest.fixture
def failing_rm(env, tmp_path):
    """A fake `rm` that cannot delete the script's RAM directory (simulated cleanup failure)."""
    e, _ = env
    fake = tmp_path / "bin" / "rm"
    fake.write_text('#!/bin/sh\nfor a in "$@"; do case "$a" in */diski9-f3.*) exit 1 ;; esac; done\n'
                    'exec /bin/rm "$@"\n')  # fmt: skip
    fake.chmod(0o755)
    before = _shm()
    yield
    for p in Path("/dev/shm").iterdir():  # remove what the simulated failure left behind
        if p.name not in before and p.name.startswith("diski9-f3."):
            shutil.rmtree(p)


def test_cleanup_failure_is_never_a_success_and_tells_the_owner_what_to_do(env, failing_rm):
    _, tmp = env
    r = _run(env)  # every step succeeds, but the RAM disk cannot be removed
    assert r.returncode == 70, r.stderr
    assert "CLEANUP FAILED" in r.stderr and "NOT successful" in r.stderr
    assert "rm -rf /dev/shm/diski9-f3." in r.stderr  # the exact manual removal command
    assert "Generate New Master Application Key" in r.stderr
    left = [p for p in Path("/dev/shm").iterdir() if p.name.startswith("diski9-f3.")]
    assert left  # the simulation really left it behind
    assert ["account", "clear"] in [c["argv"] for c in _calls(tmp)]
    _no_secrets(r)


def test_cleanup_failure_after_a_failed_step_still_warns(env, failing_rm):
    _, tmp = env
    _set(tmp, update_fail=True)
    r = _run(env)
    assert r.returncode == 70 and "CLEANUP FAILED" in r.stderr
    assert "retention update failed" in r.stderr
    _no_secrets(r)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_interrupt_at_the_prompt_cleans_up_and_stops(env, sig):
    e, tmp = env
    before = _shm()
    p = subprocess.Popen([str(SCRIPT), BUCKET], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=e, text=True)  # fmt: skip
    p.stdin.write("KEYID123\n")
    p.stdin.flush()
    deadline = time.time() + 20
    while time.time() < deadline:  # wait until the bucket has been inspected (prompt shown)
        if (tmp / "log.jsonl").exists() and '"get"' in (tmp / "log.jsonl").read_text():
            break
        time.sleep(0.05)
    time.sleep(0.3)
    p.send_signal(sig)
    out, err = p.communicate(timeout=20)
    assert p.returncode != 0
    argvs = [c["argv"] for c in _calls(tmp)]
    assert not any(a[:2] == ["bucket", "update"] for a in argvs)  # it did not continue
    assert argvs[-1] == ["account", "clear"] and _shm() == before


def test_every_b2_call_is_wrapped():
    """Static check: b2 is only invoked through b2run, or for authorize/clear with all
    output discarded."""
    for n, line in enumerate(SCRIPT.read_text().splitlines(), 1):
        code = re.sub(r'"[^"]*"', '""', line.split("#", 1)[0])  # ignore quoted messages
        for m in re.finditer(r"(?<![\w-])b2 (\w+)", code):
            if "b2run" in code or m.group(1) in ("version",):
                continue
            assert ">/dev/null 2>&1" in code, f"line {n}: unwrapped b2 call: {line.strip()}"


# ------------------------------------------------------------------ upload parsing (5.0.3)
def test_real_upload_output_with_url_lines_is_parsed(env):
    """Regression: B2 CLI 5.0.3 prints two URL lines before the JSON (the live failure)."""
    _, tmp = env
    r = _run(env)
    assert r.returncode == 0, r.stderr
    info = next(c["argv"] for c in _calls(tmp) if c["argv"][:2] == ["file", "info"])
    assert info[2] == "b2id://4_zfile1"
    _no_secrets(r)


@pytest.mark.parametrize(
    "change",
    [{"url_file_id": "4_zOTHERFILE"}, {"no_url_lines": True}, {"upload_garbage": True}],
    ids=["mismatched-ids", "no-url-line", "no-json"],
)
def test_upload_output_that_cannot_be_trusted_stops_before_inspection(env, change):
    _, tmp = env
    _set(tmp, **change)
    r = _run(env)
    assert r.returncode != 0 and "could not be parsed or its file IDs disagree" in r.stderr
    assert "--verify-canary" in r.stderr  # tells the owner how to proceed without re-uploading
    assert not any(c["argv"][:2] == ["file", "info"] for c in _calls(tmp))
    _no_secrets(r)


# ------------------------------------------------------------------ --verify-canary
GOV30 = {"mode": "governance", "period": {"duration": 30, "unit": "days"}}
NAME = "diski9/canary/setup-20261122T160000Z.txt"


def _canary(fid="4_zcanary1", ts=1795000000000, mode="governance", days=30, hold=None,
            name=NAME, action="upload"):  # fmt: skip
    return {"fileId": fid, "fileName": name, "action": action, "uploadTimestamp": ts,
            "fileRetention": {"mode": mode, "retainUntilTimestamp": ts + days * 86400000},
            "legalHold": hold}  # fmt: skip


def _hide(ts=1795000000000 + 86400000 * 2, name=NAME):
    return {
        "fileId": "4_zhide1",
        "fileName": name,
        "action": "hide",
        "uploadTimestamp": ts,
        "fileRetention": {"mode": None, "retainUntilTimestamp": None},
        "legalHold": None,
    }


def _verify(env, listing, bucket_retention=GOV30, answers="KEYID123\n"):
    e, tmp = env
    _set(tmp, listing=listing, bucket={"defaultRetention": bucket_retention})
    return subprocess.run([str(SCRIPT), "--verify-canary", BUCKET], input=answers, env=e,
                          capture_output=True, text=True, timeout=60)  # fmt: skip


FORBIDDEN = (["bucket", "update"], ["file", "upload"], ["file", "hide"], ["file", "update"],
             ["rm"], ["delete-file-version"], ["hide-file"], ["bucket", "delete"],
             ["key", "create"])  # fmt: skip


def _assert_read_only(tmp):
    argvs = [c["argv"] for c in _calls(tmp)]
    assert not any(a[: len(f)] == f for a in argvs for f in FORBIDDEN), argvs
    assert all(a[:2] in (["bucket", "get"], ["file", "info"], ["account", "authorize"],
                         ["account", "clear"]) or a[:1] in (["ls"], ["version"]) for a in argvs)  # fmt: skip


@pytest.mark.parametrize(
    "listing", [[_canary()], [_hide(), _canary()]], ids=["upload", "upload+hide"]
)
def test_verify_canary_reads_the_one_uploaded_version_without_changing_anything(env, listing):
    _, tmp = env
    before = _shm()
    r = _verify(env, listing)
    assert r.returncode == 0, r.stderr
    ev = json.loads(r.stdout[r.stdout.index("{") : r.stdout.rindex("}") + 1])
    assert ev["evidence"] == "diski9-f3-b2-canary-verification/1"
    assert ev["canary"]["fileName"] == NAME and ev["canary"]["retentionMode"] == "governance"
    assert ev["canary"]["lockDays"] == 30.0 and ev["canary"]["hideMarkers"] == len(listing) - 1
    argvs = [c["argv"] for c in _calls(tmp)]
    assert ["file", "info", "b2id://4_zcanary1"] in argvs  # the identified upload, not the marker
    assert ["ls", "--json", "--versions", "-r", f"b2://{BUCKET}/diski9/canary/"] in argvs
    _assert_read_only(tmp)
    assert "Type GOVERNANCE" not in r.stdout  # no confirmation step: nothing to change
    assert _shm() == before
    _no_secrets(r)


@pytest.mark.parametrize(
    ("listing", "bucket_retention", "message"),
    [
        ([], GOV30, "cannot be identified unambiguously"),
        ([_hide()], GOV30, "cannot be identified unambiguously"),
        ([_canary(), _canary(fid="4_zcanary2", ts=1795000100000)], GOV30, "cannot be identified unambiguously"),
        ([_canary(), _hide(ts=1795000000000 - 1000)], GOV30, "cannot be identified unambiguously"),
        ([_canary(), _hide(name="diski9/canary/setup-20261122T170000Z.txt")], GOV30, "cannot be identified unambiguously"),
        ([_canary(name="diski9/canary/other.txt")], GOV30, "cannot be identified unambiguously"),
        ([_canary(action="start")], GOV30, "cannot be identified unambiguously"),
        ([_canary(mode="compliance")], GOV30, "NOT governance-locked"),
        ([_canary(mode=None)], GOV30, "NOT governance-locked"),
        ([_canary(days=1)], GOV30, "does not expire ~30 days"),
        ([_canary(hold="on")], GOV30, "unexpected legal hold"),
        ([_canary()], {"mode": None}, "default retention is not governance/30 days"),
    ],
    ids=["none", "hide-only", "two-uploads", "hide-older-than-upload", "hide-other-name",
         "unexpected-name", "unfinished-upload", "compliance", "no-lock", "short-lock",
         "legal-hold", "bucket-not-governance"],
)  # fmt: skip
def test_verify_canary_fails_closed(env, listing, bucket_retention, message):
    _, tmp = env
    before = _shm()
    r = _verify(env, listing, bucket_retention)
    assert r.returncode != 0 and message in r.stderr, r.stderr
    _assert_read_only(tmp)
    assert _calls(tmp)[-1]["argv"] == ["account", "clear"] and _shm() == before
    _no_secrets(r)


def test_verify_canary_malformed_listing_fails_closed(env):
    e, tmp = env
    fake = tmp / "bin" / "b2"
    fake.write_text(fake.read_text().replace('print("[")  #', 'print("<html>")  #'))
    r = _verify(env, [_canary()])
    assert r.returncode != 0 and "cannot be identified unambiguously" in r.stderr
    _assert_read_only(tmp)


def test_verify_canary_cleanup_failure_is_never_a_success(env, failing_rm):
    _, tmp = env
    r = _verify(env, [_canary()])
    assert r.returncode == 70 and "CLEANUP FAILED" in r.stderr
    assert "Generate New Master Application Key" in r.stderr
    _assert_read_only(tmp)
    _no_secrets(r)


def test_verify_mode_code_path_contains_no_mutating_command():
    """Static proof: the --verify-canary branch and the helpers it uses never contain a
    bucket update, upload, hide, retention change or deletion."""
    text = SCRIPT.read_text()
    verify = text[
        text.index('echo "== verify the existing canary') : text.index(
            "\nfi\n", text.index('echo "== verify the existing canary')
        )
    ]
    helpers = text[
        text.index(
            "# ---------------------------------------------------------------- helpers"
        ) : text.index('if [ "$mode" = configure ]; then')
    ]
    for part in (verify, helpers):
        code = "\n".join(line.split("#", 1)[0] for line in part.splitlines())
        for word in (
            "bucket update",
            "file upload",
            "file hide",
            "file update",
            " rm ",
            "delete",
            "hide-file",
            "--default-retention-mode",
            "bypass",
        ):
            assert word not in code, word
    # and the mutating calls exist only inside the configure branch
    configure = text[
        text.index('if [ "$mode" = configure ]; then') : text.index(
            'echo "== verify the existing canary'
        )
    ]
    assert "bucket update" in configure and "file upload" in configure
    assert (
        text.count('b2run "retention update"') == 1 and text.count("file upload --no-progress") == 1
    )


def test_usage_rejects_extra_arguments(env):
    e, tmp = env
    r = subprocess.run([str(SCRIPT), "--verify-canary", BUCKET, "extra"], input="", env=e,
                       capture_output=True, text=True)  # fmt: skip
    assert r.returncode != 0 and "usage" in r.stderr
    assert not (tmp / "log.jsonl").exists()
