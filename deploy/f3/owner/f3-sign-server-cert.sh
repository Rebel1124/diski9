#!/usr/bin/env bash
# Diski 9 Stage F3 (owner computer): one-shot private CA for the WireGuard HTTPS address.
#
#   deploy/f3/owner/f3-sign-server-cert.sh SERVER_CSR [OUTPUT_DIR]
#
# SERVER_CSR comes from deploy/f3/host/f3-make-server-csr.sh on the VPS (public data:
# the server's private key never leaves the VPS). This script:
#   1. creates a RAM-only scratch directory (lib-ramdir.sh);
#   2. generates the CA private key there (EC P-256) and a CA certificate
#      (CA:TRUE, pathlen:0, keyCertSign/cRLSign, F3_DAYS days);
#   3. signs exactly one server certificate: CA:FALSE, digitalSignature, serverAuth,
#      subjectAltName = IP:<F3_IP> only (CSR extensions are ignored);
#   4. verifies the chain for the IP and the SAN;
#   5. destroys the CA private key with the RAM directory, so no further certificate
#      can ever be issued under this root. No name constraint is used or relied on.
# Output (OUTPUT_DIR, default ./diski9-f3-tls):
#   diski9-f3-ca.crt / .cer   root certificate (PEM / DER) -> install on peer devices
#   server.crt                -> /etc/diski9/tls/server.crt on the VPS
#   fingerprints.txt          SHA-256 fingerprints to compare on each device
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib-ramdir.sh
. "$here/lib-ramdir.sh"

csr=${1:?usage: f3-sign-server-cert.sh SERVER_CSR [OUTPUT_DIR]}
out=${2:-./diski9-f3-tls}
ip=${F3_IP:-10.88.0.1}
days=${F3_DAYS:-180}
command -v openssl >/dev/null || f3_die "openssl is required"
[ -f "$csr" ] || f3_die "CSR not found: $csr"
[[ "$ip" =~ ^10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] || f3_die "F3_IP must be a 10.x tunnel address"
[ "$days" -ge 1 ] && [ "$days" -le 397 ] || f3_die "F3_DAYS must be 1..397"
[ -e "$out" ] && f3_die "$out already exists: refusing to overwrite"

openssl req -in "$csr" -noout -verify >/dev/null 2>&1 || f3_die "CSR signature does not verify"
keyinfo=$(openssl req -in "$csr" -noout -text)
grep -q "ASN1 OID: prime256v1" <<<"$keyinfo" || f3_die "CSR key must be EC P-256"

umask 077
mkdir -p "$out"
f3_ramdir_create
cakey="$F3_RAMDIR/ca.key"
openssl ecparam -name prime256v1 -genkey -noout -out "$cakey"
cat > "$F3_RAMDIR/ca.cnf" <<CNF
[req]
distinguished_name=dn
prompt=no
[dn]
CN=Diski 9 F3 private CA (one-shot $(date -u +%Y-%m-%d))
[v3_ca]
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
CNF
cat > "$F3_RAMDIR/leaf.cnf" <<CNF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectAltName=IP:$ip
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid
CNF
openssl req -x509 -new -key "$cakey" -sha256 -days "$days" -config "$F3_RAMDIR/ca.cnf" \
  -extensions v3_ca -out "$out/diski9-f3-ca.crt"
openssl x509 -req -in "$csr" -CA "$out/diski9-f3-ca.crt" -CAkey "$cakey" \
  -set_serial "0x$(openssl rand -hex 16)" -sha256 -days "$days" \
  -extfile "$F3_RAMDIR/leaf.cnf" -out "$out/server.crt" 2>/dev/null

# the CA key is no longer needed: destroy it now, before anything else can go wrong
f3_ramdir_destroy
trap - EXIT INT TERM

openssl verify -CAfile "$out/diski9-f3-ca.crt" -verify_ip "$ip" "$out/server.crt" >/dev/null \
  || f3_die "server certificate does not verify for $ip"
san=$(openssl x509 -in "$out/server.crt" -noout -ext subjectAltName | tail -n +2 | tr -d ' ')
[ "$san" = "IPAddress:$ip" ] || f3_die "unexpected subjectAltName: $san"
openssl x509 -in "$out/diski9-f3-ca.crt" -outform DER -out "$out/diski9-f3-ca.cer"
{
  echo "CA     $(openssl x509 -in "$out/diski9-f3-ca.crt" -noout -fingerprint -sha256 | cut -d= -f2)"
  echo "server $(openssl x509 -in "$out/server.crt" -noout -fingerprint -sha256 | cut -d= -f2)"
  echo "valid  $(openssl x509 -in "$out/server.crt" -noout -enddate | cut -d= -f2) (server)"
  echo "SAN    IP:$ip"
} > "$out/fingerprints.txt"
chmod 0644 "$out"/*
cat "$out/fingerprints.txt"
echo "CA private key destroyed (it existed only in a RAM-backed directory)."
