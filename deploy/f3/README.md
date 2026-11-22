# Stage F3 scripts (Phase 6C.6)

Version-controlled scripts for the private F3 environment. **The owner runs every one of
them**; Claude never holds a credential. The sequence, the evidence to return and the
gates are in [`docs/operations_f3_owner_setup.md`](../../docs/operations_f3_owner_setup.md).

| Script | Where it runs | What it does |
|---|---|---|
| `owner/f3-make-age-identities.sh` | owner's computer | two passphrase-encrypted `age` identities (plaintext keys only in memory), public recipients, round-trip check |
| `owner/f3-sign-server-cert.sh` | owner's computer | one-shot private CA in a RAM disk: signs the server CSR with `subjectAltName=IP:10.88.0.1`, verifies it, destroys the CA key |
| `owner/lib-ramdir.sh` | (sourced) | RAM-disk / tmpfs scratch directory, refused if not memory-backed |
| `host/f3-make-server-csr.sh` | server (root) | server TLS key (stays on the server) and CSR |
| `host/f3_day1_check.py` | server | read-only day-one check: system facts, IPv6, listening ports, TCP timing to the named database hosts; public IPs masked |

No script reads a secret from an argument or the environment, prints a private key, or
contacts any host the owner did not name.
