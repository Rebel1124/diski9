#!/usr/bin/env bash
# Diski 9 Stage F3 (owner computer): set and verify the B2 bucket's default retention
# (Governance, 30 days) and prove it on a canary upload. Run once, with the master key.
#
#   deploy/f3/owner/f3-b2-configure-governance.sh BUCKET_NAME                  (configure)
#   deploy/f3/owner/f3-b2-configure-governance.sh --verify-canary BUCKET_NAME  (read-only)
#
# --verify-canary changes nothing: it re-checks the bucket (Governance 30 days already
# set), finds the ONE uploaded canary version under diski9/canary/ (lifecycle hide
# markers are recognised and ignored; anything ambiguous fails), reads that exact
# version's retention by file ID and prints the evidence. It never uploads, never
# updates the bucket and never deletes or hides anything.
#
# Before running: the bucket exists (private, Object Lock enabled, NO default retention
# set in the web UI, lifecycle rules entered), and you have just generated a master
# application key in the web UI (keyID + key shown once; do not save them).
#
# Credential handling (B2 CLI 5.x behaviour, read from its source):
#  * the key ID is read here without echo and given to `b2 account authorize` only through
#    that one process's environment; the application key is typed at b2's own hidden
#    prompt (getpass on the terminal): never an argument, never exported, never in history;
#  * `b2 account authorize` prints the key and auth token as JSON on success, so its
#    standard output is discarded; `b2 account get` (which does the same) is never used;
#  * b2 caches the key in an SQLite file: B2_ACCOUNT_INFO points it into a RAM disk;
#  * on any exit (success, error, Ctrl-C) the cache is cleared and the RAM disk destroyed.
# After the script: generate a NEW master key in the web UI (invalidates the one used;
# standard keys are unaffected) and do not save it.
#
# The retention mode is fixed to governance in this script: compliance is irreversible
# and is never set here. No key is created; nothing is deleted.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib-ramdir.sh
. "$here/lib-ramdir.sh"

mode=configure
if [ "${1:-}" = "--verify-canary" ]; then
  mode=verify
  shift
fi
bucket=${1:?usage: f3-b2-configure-governance.sh [--verify-canary] BUCKET_NAME}
[ $# -eq 1 ] || f3_die "usage: f3-b2-configure-governance.sh [--verify-canary] BUCKET_NAME"
[[ "$bucket" =~ ^diski9-f3-[0-9a-f]{8}$ ]] || f3_die "bucket name must be diski9-f3-<8 hex>"
command -v b2 >/dev/null || f3_die "install the B2 CLI: brew install b2-tools"
command -v python3 >/dev/null || f3_die "python3 is required (installed with b2-tools)"
if [ -n "${B2_APPLICATION_KEY:-}${B2_APPLICATION_KEY_ID:-}" ]; then
  f3_die "unset B2_APPLICATION_KEY / B2_APPLICATION_KEY_ID first (keys must not be in the environment)"
fi
[ -e "$HOME/.b2_account_info" ] && echo "warning: ~/.b2_account_info exists (an older b2 login cache, possibly holding a key); it is not used here — delete it with: b2 account clear (without B2_ACCOUNT_INFO set)" >&2

export F3_BUCKET="$bucket"
f3_ramdir_create
export B2_ACCOUNT_INFO="$F3_RAMDIR/b2_account_info"
cleanup() {
  local rc=$?
  trap - EXIT INT TERM HUP
  b2 account clear >/dev/null 2>&1 || true
  if ! f3_ramdir_destroy; then
    {
      echo
      echo "!!! CLEANUP FAILED: the RAM disk may still hold the b2 login cache, which contains"
      echo "!!! the MASTER KEY. This run is NOT successful, whatever was printed above."
      echo "!!!  1. Remove it now: ${F3_RAMDEV_LEFT:+hdiutil detach $F3_RAMDEV_LEFT -force}${F3_RAMDEV_LEFT:-rm -rf $F3_RAMDIR_LEFT}"
      echo "!!!     (check with: hdiutil info / ls /Volumes; a restart also discards a RAM disk)"
      echo "!!!  2. Rotate the master key IMMEDIATELY: web UI > App Keys >"
      echo "!!!     Generate New Master Application Key (do not save the new one)."
    } >&2
    exit 70
  fi
  exit "$rc"
}
# one cleanup path: EXIT always runs it; signals turn into an exit (never continue)
trap cleanup EXIT
trap 'echo "interrupted: cleaning up" >&2; exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# b2run STEP OUTFILE ARGS...: run b2 with BOTH output streams captured in the RAM disk.
# Nothing b2 prints ever reaches the terminal, on success or failure: a failure shows a
# fixed, step-specific message only. The raw response stays in the RAM disk (destroyed
# on exit); it is never printed or scrubbed-and-printed.
b2run() {
  local step=$1 out=$2
  shift 2
  if ! b2 "$@" >"$out" 2>"$F3_RAMDIR/b2-error.txt"; then
    f3_die "$step failed (b2 reported an error; its raw message is not shown for safety). Nothing further was done; see the runbook (O-6) before retrying"
  fi
}

# no b2 command runs before its cache points into the RAM disk
b2run "b2 version" "$F3_RAMDIR/version.txt" version
grep -Eq "version (4|5)\." "$F3_RAMDIR/version.txt" || f3_die "B2 CLI 4.x or 5.x required"

check() { # check <json file> <python expression over d> <message>; unreadable JSON fails too
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if ($2) else 1)" "$1" \
    2>/dev/null || f3_die "$3"
}

LIFECYCLE='[{"daysFromHidingToDeleting":30,"daysFromUploadingToHiding":14,"fileNamePrefix":"diski9/daily/"},{"daysFromHidingToDeleting":30,"daysFromUploadingToHiding":56,"fileNamePrefix":"diski9/weekly/"},{"daysFromHidingToDeleting":30,"daysFromUploadingToHiding":1,"fileNamePrefix":"diski9/canary/"}]'
export LIFECYCLE
LC_OK='sorted(map(json.dumps, [{k: r.get(k) for k in ("daysFromHidingToDeleting","daysFromUploadingToHiding","fileNamePrefix")} for r in d.get("lifecycleRules", [])]), key=str) == sorted(map(json.dumps, json.loads(__import__("os").environ["LIFECYCLE"])), key=str)'

echo "== sign in with the master key (nothing is printed or stored on disk)"
printf 'Master application keyID (input hidden): '
IFS= read -rs kid
echo
[ -n "$kid" ] || f3_die "no keyID entered"
# authorize prints the key and token on success; its output, success or failure, is discarded
if ! B2_APPLICATION_KEY_ID="$kid" b2 account authorize >/dev/null 2>&1; then
  unset kid
  f3_die "authorisation failed (wrong key, expired key or no network); nothing was changed"
fi
unset kid

echo "== inspect the bucket"
b2run "bucket inspection" "$F3_RAMDIR/before.json" bucket get "$bucket"
check "$F3_RAMDIR/before.json" 'd.get("bucketName") == __import__("os").environ["F3_BUCKET"]' \
  "b2 returned a different or unreadable bucket record"
check "$F3_RAMDIR/before.json" 'd.get("isFileLockEnabled") is True' \
  "Object Lock is NOT enabled on $bucket: stop (do not upload anything)"
check "$F3_RAMDIR/before.json" 'd.get("bucketType") == "allPrivate"' "$bucket is not private: stop"
check "$F3_RAMDIR/before.json" '(d.get("defaultRetention") or {}).get("mode") in (None, "none", "governance")' \
  "a COMPLIANCE (or unknown) default retention is set on $bucket: stop and report (do not upload anything)"
check "$F3_RAMDIR/before.json" "$LC_OK" "lifecycle rules differ from the approved rules: fix them in the web UI first"

# ---------------------------------------------------------------- helpers
# upload_file_id FILE: the file ID from `b2 file upload` output. B2 CLI 5.0.3 prints two
# text lines ("URL by file name: ...", "URL by fileId: ...?fileId=<id>") and THEN the
# JSON file version. Both IDs must be present and agree; otherwise this fails.
upload_file_id() {
  python3 - "$1" <<'PY' 2>/dev/null
import json, re, sys, urllib.parse
text = open(sys.argv[1], encoding="utf-8", errors="strict").read()
lines = text.splitlines()
url_ids = [urllib.parse.parse_qs(urllib.parse.urlsplit(l.split(": ", 1)[1]).query).get("fileId", [None])[0]
           for l in lines if l.startswith("URL by fileId: ")]
starts = [i for i, l in enumerate(lines) if l.startswith("{")]
if len(url_ids) != 1 or not url_ids[0] or not starts:
    sys.exit(1)
body = "\n".join(lines[starts[0]:])
obj, end = json.JSONDecoder().raw_decode(body)
if body[end:].strip() or not isinstance(obj, dict):
    sys.exit(1)
fid = obj.get("fileId")
if not isinstance(fid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", fid) or fid != url_ids[0]:
    sys.exit(1)
print(fid)
PY
}

# inspect_canary FILEID: read that exact version and require Governance, an expiry
# ~30 days after upload, the canary name, and no legal hold
inspect_canary() {
  export F3_FID="$1"
  b2run "canary inspection" "$F3_RAMDIR/info.json" file info "b2id://$1"
  check "$F3_RAMDIR/info.json" 'd.get("fileId") == __import__("os").environ["F3_FID"] and __import__("re").fullmatch(r"diski9/canary/setup-\d{8}T\d{6}Z\.txt", d.get("fileName", ""))' \
    "file info did not return the canary version that was identified"
  check "$F3_RAMDIR/info.json" '(d.get("fileRetention") or {}).get("mode") == "governance"' \
    "the canary is NOT governance-locked: stop, upload nothing, report"
  check "$F3_RAMDIR/info.json" 'abs(d["fileRetention"]["retainUntilTimestamp"] - d["uploadTimestamp"] - 30*86400000) <= 3600000' \
    "the canary's lock does not expire ~30 days after upload: stop and report"
  check "$F3_RAMDIR/info.json" 'd.get("legalHold") in (None, "off", "unset")' \
    "the canary has an unexpected legal hold: stop and report"
}

# find_canary FILE: from `b2 ls --json --versions` output, the file ID of the ONE uploaded
# canary version. Lifecycle hide markers (action "hide") for that same name, newer than
# the upload, are recognised and ignored. Zero or several uploads, any other action, any
# other name, or a malformed listing fails: nothing is ever picked arbitrarily.
find_canary() {
  python3 - "$1" <<'PY' 2>/dev/null
import json, re, sys
items = json.load(open(sys.argv[1]))
if not isinstance(items, list):
    sys.exit(1)
name_re = re.compile(r"diski9/canary/setup-\d{8}T\d{6}Z\.txt")
uploads, hides = [], []
for it in items:
    if not isinstance(it, dict) or not name_re.fullmatch(str(it.get("fileName", ""))):
        sys.exit(1)
    action = it.get("action")
    if action == "upload":
        uploads.append(it)
    elif action == "hide":
        hides.append(it)
    else:
        sys.exit(1)
if len(uploads) != 1:
    sys.exit(1)
up = uploads[0]
for h in hides:
    if h.get("fileName") != up.get("fileName") or h.get("uploadTimestamp", 0) <= up.get("uploadTimestamp", 0):
        sys.exit(1)
fid = up.get("fileId")
if not isinstance(fid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", fid):
    sys.exit(1)
print(fid, len(hides))
PY
}

if [ "$mode" = configure ]; then
echo "== set the default retention: GOVERNANCE, 30 days"
printf 'Type GOVERNANCE to set it on %s: ' "$bucket"
IFS= read -r answer
[ "$answer" = "GOVERNANCE" ] || f3_die "not confirmed; nothing was changed"
b2run "retention update" "$F3_RAMDIR/update.json" bucket update \
  --default-retention-mode governance --default-retention-period "30 days" "$bucket"
b2run "bucket re-inspection" "$F3_RAMDIR/after.json" bucket get "$bucket"
check "$F3_RAMDIR/after.json" '(d.get("defaultRetention") or {}) == {"mode": "governance", "period": {"duration": 30, "unit": "days"}}' \
  "default retention is not governance/30 days after the update: stop, upload nothing, report"
check "$F3_RAMDIR/after.json" 'd.get("bucketType") == "allPrivate" and d.get("isFileLockEnabled") is True' \
  "bucket type or Object Lock changed unexpectedly: stop and report"
check "$F3_RAMDIR/after.json" "$LC_OK" "lifecycle rules changed unexpectedly: stop and report"

echo "== canary: upload one small file and read the retention of THAT version"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
printf 'diski9-f3 retention canary %s\n' "$stamp" > "$F3_RAMDIR/canary.txt"
b2run "canary upload" "$F3_RAMDIR/upload.json" file upload --no-progress "$bucket" \
  "$F3_RAMDIR/canary.txt" "diski9/canary/setup-$stamp.txt"
fid=$(upload_file_id "$F3_RAMDIR/upload.json") \
  || f3_die "the upload response could not be parsed or its file IDs disagree: stop and report (do not upload again; verify with --verify-canary)"
inspect_canary "$fid"

else
echo "== verify the existing canary (read-only: no upload, no bucket change, no deletion)"
check "$F3_RAMDIR/before.json" '(d.get("defaultRetention") or {}) == {"mode": "governance", "period": {"duration": 30, "unit": "days"}}' \
  "the bucket's default retention is not governance/30 days: stop and report"
b2run "canary listing" "$F3_RAMDIR/list.json" ls --json --versions -r "b2://$bucket/diski9/canary/"
found=$(find_canary "$F3_RAMDIR/list.json") \
  || f3_die "the canary cannot be identified unambiguously (none, several uploads, or unexpected entries): stop and report"
read -r fid hides <<<"$found"
export F3_HIDES="$hides"
inspect_canary "$fid"
cp "$F3_RAMDIR/before.json" "$F3_RAMDIR/after.json"

fi

echo "== evidence (no account ID, bucket ID, file ID, key or token)"
F3_MODE="$mode" python3 - "$F3_RAMDIR/after.json" "$F3_RAMDIR/info.json" <<'PY'
import datetime as dt, json, os, sys
b, f = (json.load(open(p)) for p in sys.argv[1:3])
iso = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(json.dumps({
    "evidence": "diski9-f3-b2-governance/1" if os.environ["F3_MODE"] == "configure"
                else "diski9-f3-b2-canary-verification/1",
    "verifiedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "bucketName": b["bucketName"], "bucketType": b["bucketType"],
    "isFileLockEnabled": b["isFileLockEnabled"], "defaultRetention": b["defaultRetention"],
    "lifecycleRules": b["lifecycleRules"],
    "canary": {"fileName": f["fileName"], "uploaded": iso(f["uploadTimestamp"]),
               "retentionMode": f["fileRetention"]["mode"],
               "retainUntil": iso(f["fileRetention"]["retainUntilTimestamp"]),
               "lockDays": round((f["fileRetention"]["retainUntilTimestamp"] - f["uploadTimestamp"]) / 86400000, 3),
               "legalHold": f.get("legalHold"),
               "hideMarkers": int(os.environ.get("F3_HIDES", "0"))},
}, indent=2))
PY
echo
echo "Done. Now, in the web UI: App Keys > Generate New Master Application Key (do not save it)."
echo "That invalidates the key just used; then confirm no other application keys exist."
