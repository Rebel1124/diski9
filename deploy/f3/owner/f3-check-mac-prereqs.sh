#!/usr/bin/env bash
# Diski 9 Stage F3 (owner computer): read-only prerequisite check. Changes nothing.
#
#   deploy/f3/owner/f3-check-mac-prereqs.sh
#
# Prints each prerequisite as OK / MISSING / CHECK, then a summary. Safe to share the
# output: it contains version numbers and yes/no answers only (no names, keys or paths
# under your home folder).
set -euo pipefail
missing=0
ok() { printf '  OK       %-22s %s\n' "$1" "$2"; }
bad() { printf '  MISSING  %-22s %s\n' "$1" "$2"; missing=$((missing + 1)); }
chk() { printf '  CHECK    %-22s %s\n' "$1" "$2"; }

echo "Diski 9 F3 owner-computer prerequisites"
os=$(uname -s)
if [ "$os" = "Darwin" ]; then
  ok "macOS" "$(sw_vers -productVersion) ($(uname -m))"
  if fdesetup status 2>/dev/null | grep -q "FileVault is On"; then
    ok "FileVault" "on"
  else
    bad "FileVault" "off: System Settings > Privacy & Security > FileVault"
  fi
  if command -v brew >/dev/null; then ok "Homebrew" "$(brew --version | head -1)"; else
    bad "Homebrew" "install from https://brew.sh"; fi
else
  chk "operating system" "$os (not macOS: use the Linux notes in the runbook)"
fi

if command -v git >/dev/null; then ok "git" "$(git --version)"; else bad "git" "brew install git"; fi
if command -v ssh-keygen >/dev/null; then ok "ssh / ssh-keygen" "$(ssh -V 2>&1)"; else
  bad "ssh-keygen" "part of macOS; reinstall the command line tools"; fi

ossl=$(command -v openssl || true)
case "$(openssl version 2>/dev/null)" in
  "OpenSSL 3."* | "OpenSSL 4."*) ok "openssl (on PATH)" "$(openssl version)" ;;
  *) bad "openssl (on PATH)" "found '$(openssl version 2>/dev/null || echo none)' at ${ossl:-?}: brew install openssl@3 and put it first on PATH" ;;
esac

if command -v age >/dev/null && command -v age-keygen >/dev/null; then
  v=$(age --version | sed 's/^v//')
  case "$v" in
    1.[1-9]* | 1.[1-9][0-9]* | [2-9].*) ok "age" "$v" ;;
    *) bad "age" "$v is too old (need 1.1 or later): brew upgrade age" ;;
  esac
else
  bad "age" "brew install age"
fi

if [ -n "$(git rev-parse --show-toplevel 2>/dev/null || true)" ]; then
  ok "repository" "branch $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)"
  if [ -n "$(git status --porcelain)" ]; then chk "working tree" "has local changes"; else
    ok "working tree" "clean"; fi
else
  chk "repository" "run this from inside your diski9 clone"
fi

echo
if [ "$missing" -eq 0 ]; then echo "All prerequisites present."; else
  echo "$missing prerequisite(s) missing: fix them, then run this again."; fi
