#!/usr/bin/env bash
# Diski 9 Stage F3 (VPS, as root): create the HTTPS server key and its CSR.
#
#   sudo deploy/f3/host/f3-make-server-csr.sh [--dir /etc/diski9/tls] [--rotate]
#
# The private key is generated on the VPS and never leaves it. The CSR (public) is
# printed and saved as server.csr; copy it to your computer and sign it with
# deploy/f3/owner/f3-sign-server-cert.sh, then copy server.crt back into the same dir.
# The key is readable by root and the "caddy" group only (if that group exists).
set -euo pipefail
dir=/etc/diski9/tls
rotate=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) dir=$2; shift 2 ;;
    --rotate) rotate=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }
if [ -e "$dir/server.key" ] && [ "$rotate" -ne 1 ]; then
  echo "error: $dir/server.key exists; use --rotate to replace it deliberately" >&2
  exit 1
fi
umask 077
install -d -m 0750 "$dir"
openssl ecparam -name prime256v1 -genkey -noout -out "$dir/server.key.new"
openssl req -new -key "$dir/server.key.new" -subj "/CN=diski9-f3" -out "$dir/server.csr"
mv -f "$dir/server.key.new" "$dir/server.key"
if getent group caddy >/dev/null 2>&1; then
  chgrp caddy "$dir" "$dir/server.key"
  chmod 0640 "$dir/server.key"
fi
chmod 0644 "$dir/server.csr"
echo "Key: $dir/server.key (stays on this server)"
echo "CSR: $dir/server.csr (public; copy it to your computer):"
cat "$dir/server.csr"
