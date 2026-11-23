# Stage F3 owner setup and checkpoint runbook

**Status:** Phase 6C.6 Stage F3 **implementation authorised by the owner (22 Nov 2026)**.
This is the **Checkpoint 0** deliverable: the owner's setup sequence, scripts,
prerequisites and verification checklists.
* Nothing has been purchased, subscribed, provisioned or accessed.
* Every financial transaction and every account is created by the owner personally.

Decisions: [`architecture/phase6c6_stage_f3_plan.md`](architecture/phase6c6_stage_f3_plan.md)
§X and §Y. Scripts: [`../deploy/f3/`](../deploy/f3/README.md). General host runbook:
[`operations_hosting.md`](operations_hosting.md).

**Scope:** the authorisation covers Stage F3 only.

**Never in F3:**
* F4 or F5;
* public deployment;
* live API-Football calls (the server holds no API-Football key);
* participant accounts;
* production release, merge, tag or release.

**Safeguards kept throughout:**
* provider calls off and refresh off;
* Official disabled;
* human-only publication;
* no live SQLite replacement;
* D-29b schedule unchanged;
* Stage D locking unchanged.

F3-D10 (automatic hold activation) and F3-D11 (manual provider commands) stay **deferred
until before F4**.

## 1. Ground rules

### 1.1 Who does what

| | Owner (personally) | Claude |
|---|---|---|
| Money | every purchase, subscription and card payment | never |
| Accounts | creates every account, turns on MFA, holds every login | never holds a login |
| Secrets | generates, stores and moves every password, key and passphrase | never sees one |
| Commands on the server or the owner's computer | runs them from this repository's scripts and runbooks | writes and version-controls the scripts; reviews the returned evidence |
| Gates | decides to proceed after each checkpoint | prepares the evidence for the decision |

### 1.2 Secrets: never in chat, never on a command line

**Never send any of these to Claude, paste them into a chat, put them in a file in this
repository, or type them as a command argument:**
* passwords (Hostinger, Supabase, Backblaze, the database `postgres` password, the
  backup role password);
* Supabase API keys (publishable/anon or secret/`service_role`);
* Backblaze application keys (key ID **and** key value);
* WireGuard private or preshared keys;
* SSH private keys;
* `age` private identities (`AGE-SECRET-KEY-…`) and their passphrases;
* the private CA key (it never exists outside a RAM disk);
* MFA recovery codes.

**Public and safe to return:**
* `age1…` recipients;
* the CA and server **certificates** and their fingerprints;
* the CSR;
* the Supabase project ref;
* bucket names;
* masked IP addresses;
* the script reports below.

**Moving a secret onto the server:**
1. Copy it from your password manager into the SSH session's standard input so that it
   never reaches a command line or shell history:

   ```bash
   sudo install -m 0600 -o root -g root /dev/null /etc/diski9/<file>
   ```

   ```bash
   sudo tee /etc/diski9/<file> >/dev/null
   ```

2. After the second command, paste the value, press Enter, then Ctrl-D.

The checkpoint runbooks name each file.

### 1.3 Returning evidence

* Return the scripts' reports as produced. Public IP addresses are already masked.
* Prefer text to screenshots. If you send a screenshot, check that no key, password,
  token, connection string with a password, or full public IP is visible.
* Before sending anything, search it for: `password`, `secret`, `AGE-SECRET-KEY`,
  `eyJ`, `sb_secret_`, `service_role`, `PRIVATE KEY`, `applicationKey`, and `@` inside a
  URL. If any appears, do not send it.

## 2. Checkpoints and hard-stop gates

Every checkpoint ends with a **STOP for owner review**. The next checkpoint starts only
on the owner's instruction.

| CP | Work | Gate (hard stop unless stated) |
|---|---|---|
| **0** | owner setup instructions, scripts, prerequisites, checklists (**this document**) | owner review |
| **1** | owner accounts and purchases (§4); day-one host check | **G1**: IT-1 VPS-to-Supabase database RTT **p95 strictly below 10 ms** (methodology: plan §Z.8; it also decides final acceptance of the Düsseldorf location, F3-D1a/F3-D2a), IT-2 IPv6 (else session pooler or IPv4 add-on), IT-9 console. A failure means a fallback decision inside the refund window |
| 2 | host hardening; WireGuard; private HTTPS (one-shot CA); public SSH closed | **G2 (private network access)**: only the WireGuard UDP port reachable from the internet (external scan); site and SSH only through the tunnel; certificate trusted on each real device (IT-6) |
| 3 | application install at a recorded commit; Supabase configuration (migrations to `app_0007`, Auth settings, email templates, owner bootstrap); database TLS | **G3a (database TLS)**: `verify-full` with the pinned CA on every endpoint; plaintext refused (IT-4, IT-10). **G3b (hosted advisory locking)**: the Stage D lock probe passes on the chosen scheduler endpoint (IT-3). Any failure stops F3 |
| 4 | backups: restricted backup role (IT-11), B2 key tests N1–N9/P1 (IT-7), nightly encrypted copies for ≥ 3 nights, weekly inventory | **G4 (backup credential restrictions)**: every negative test refused as specified; restricted role proven; levels 1–3 in `ops status` |
| 5 | recovery drills M1 and M3; completeness verification (§6); target-database-first provider hold; operator sign-in; SQLite restore to a new path plus offline switch | **G5 (recovery validation)**: level-4 evidence; completeness matches; hold verified before cutover; operator signs in |
| 6 | failure injection; 72-hour scheduler soak (provider calls off); browser smoke and South African timings | soak and timings reported; any lock or recovery regression is a hard stop |
| 7 | F3 acceptance report: hosted evidence kept separate from local evidence, costs, residual risks | **owner acceptance** (separate decision) |

## 3. Prerequisites (before Checkpoint 1)

### 3.1 On the owner's computer (macOS)
* macOS, up to date, with **FileVault on** (System Settings → Privacy & Security →
  FileVault).
* **Homebrew** (https://brew.sh) and these tools:

  | Tool | Install | Why |
  |---|---|---|
  | Git | `brew install git` (or Apple's command line tools) | the repository |
  | GitHub CLI | `brew install gh`, then `gh auth login` (browser sign-in; no token is ever pasted anywhere) | cloning the private repository |
  | OpenSSL 3 | `brew install openssl@3`; it is *keg-only*, so put it first on `PATH` (below) | the one-shot CA (Checkpoint 2); macOS's built-in `openssl` is LibreSSL and is refused by the script |
  | age | `brew install age` (1.3.2 at the time of writing; Apple Silicon has a ready-made bottle, Intel Macs build it from source automatically) | backup identities |
  | SSH | built into macOS (`ssh`, `ssh-keygen`) | server login |
  | WireGuard | App Store | Checkpoint 2 |
  | PostgreSQL 17 client | `brew install postgresql@17` | from Checkpoint 4 only |

* **OpenSSL 3 on PATH** (zsh, the macOS default shell):

  ```bash
  echo 'export PATH="$(brew --prefix openssl@3)/bin:$PATH"' >> ~/.zprofile
  ```

  Then open a new Terminal window.
* **Check everything with the read-only checker** (changes nothing; its output is safe
  to share):

  ```bash
  deploy/f3/owner/f3-check-mac-prereqs.sh
  ```

* **`age` compatibility:**
  * The scripts need age ≥ 1.1 (passphrase-encrypted identity files used with `-i`) and
    refuse older versions.
  * They were tested end to end with **age 1.1.1 and 1.3.2** (the Homebrew version on
    22 Nov 2026).
  * The identity format is the standard X25519 `age1…` / `AGE-SECRET-KEY-1…`. The
    optional post-quantum keys of age 1.3 (`-pq`) are **not** used.
  * Each identity is stored as an ASCII-armoured, passphrase-encrypted age file
    (`-----BEGIN AGE ENCRYPTED FILE-----`).
  * `age -d -i <identity>.age <file>` asks for the identity's passphrase, then decrypts.
* Linux works too: tmpfs `/dev/shm` instead of a RAM disk, and swap encrypted or off.

### 3.2 Accounts and means
* A **password manager** with MFA. Create empty entries now, named exactly as in §7.
* An **authenticator app** on your phone for MFA (TOTP); store recovery codes in the
  password manager.
* A **payment card**, not crypto: Hostinger's 30-day money-back guarantee excludes some
  methods.
* Your **phone** with the official WireGuard app, as the second peer.
* A small **offline medium** (encrypted USB stick, or paper) and a separate place to
  keep it, for the offline-recovery `age` identity.

## 4. Owner setup sequence (Checkpoint 1)

This order refines §X.5: Supabase now comes before Hostinger. The day-one check then has
its database targets as soon as the server exists, and the refund clock starts as late
as possible.

### O-1 Password manager, MFA and an SSH key (no cost)

1. Create the password-manager entries listed in §7, still empty.
2. Generate the SSH key used to log in to the server, with a passphrase from the password
   manager:

   ```bash
   ssh-keygen -t ed25519 -a 100 -C diski9-f3-owner -f ~/.ssh/diski9_f3
   ```

3. The public half, `~/.ssh/diski9_f3.pub`, is given to Hostinger in O-4. The private
   half never leaves your computer.

**Return:** "O-1 done" and the SSH public key's fingerprint
(`ssh-keygen -lf ~/.ssh/diski9_f3.pub`).

### O-2 Backup encryption identities (no cost)

1. Generate two long random passphrases in the password manager: entries
   *age primary passphrase* and *age offline passphrase*.
2. Run:

   ```bash
   deploy/f3/owner/f3-make-age-identities.sh
   ```

   Type each passphrase when asked (twice each, then once each for the round-trip
   check). The plaintext private keys exist only in memory: `age-keygen` is piped
   straight into `age -p`.
3. Store `diski9-f3-age-primary.age` as an attachment in the password manager.
4. Copy `diski9-f3-age-offline-recovery.age` to the offline medium. Write its passphrase
   on paper, kept **separately** from that medium.
5. Delete the two `.age` files from the folder. They are encrypted; this is
   housekeeping.

**Return:** the two `age1…` lines from `diski9-f3-age-recipients.txt` (public), and
"primary: OK / offline-recovery: OK".

### O-3 Supabase Pro (first payment)

1. Create a Supabase account with **MFA on** (Account → Security). Create an
   organisation.
2. **Upgrade the organisation to Pro** with your card. Leave the **spend cap on**.
3. **Create the project:**
   * name `diski9-f3`;
   * region **Central EU (Frankfurt)**, `eu-central-1`;
   * compute **Micro** (the smallest);
   * database password: generate it in the password manager (≥ 32 random characters),
     paste it into the form, and save it as *Supabase postgres password*.
4. **Database → Settings:** turn **SSL enforcement on**. Download the **CA certificate**.
   It is public; keep the file for Checkpoint 3.
5. **Authentication → Sign In / Providers (email):**
   * **turn off "Allow new users to sign up"** now (the owner account is bootstrapped
     deliberately in Checkpoint 3);
   * turn **leaked-password protection** on.
6. **Do not** copy or share any API key. The secret/`service_role` key is **not used
   anywhere in F3**.
7. From **Connect**, note only the **host names**, never a connection string with the
   password:
   * the session pooler host (`aws-…-eu-central-1.pooler.supabase.com`);
   * the direct host (`db.<ref>.supabase.co`).

**Return:**
* the project ref;
* the region and compute size shown;
* "Pro, spend cap on";
* "SSL enforcement on";
* "signups off, leaked-password protection on";
* the two host names;
* the invoice amount and tax lines (amounts only).

### O-4 Hostinger KVM 2 (second payment; the refund clock starts)

1. Create a Hostinger account with **two-factor authentication on**.
2. **Buy:**
   * product **KVM 2**, **1-month** term;
   * location **Germany** (confirm that hPanel shows **Frankfurt**). *Provisioned VPS:
     Düsseldorf, Hostinger's only German location as the owner reports it. Kept under
     amendment F3-D1a/F3-D2a, approved for Stage F3; **final-acceptance condition met
     23 Nov 2026** (IT-1 PASS and zero-success check, plan §Z);*
   * **no** daily backups add-on;
   * **no** other add-ons;
   * pay by card.
3. **Set up the server:**
   * operating system **Ubuntu 24.04 LTS** (plain OS, no control panel or app template);
   * hostname `diski9-f3`;
   * add the SSH **public** key `~/.ssh/diski9_f3.pub`;
   * if hPanel offers to disable password login, disable it;
   * the root password requested by hPanel goes into the password manager entry
     *Hostinger VPS root password*, and is never typed into any chat.
4. Open hPanel's **browser terminal/console** once and log in. This is IT-9, the
   break-glass path, and it must work before public SSH is closed in Checkpoint 2.
5. **Write down the purchase date.** It is refund day 0. Put a calendar reminder for
   **day 25**: the last day to decide on the DigitalOcean fallback.

**Return:**
* plan, term and location exactly as hPanel shows them (data-centre name);
* OS;
* the invoice amount and tax lines;
* the purchase date;
* "console works";
* the SSH host-key fingerprint shown on first login (`ssh-keygen -lf` on the server's
  `/etc/ssh/ssh_host_ed25519_key.pub`).

### O-5 Day-one host check (gate G1, read-only)

The server does not need GitHub access: copy the one script from your Mac. Run this in
your diski9 clone; it copies a file, nothing secret:

```bash
scp -i ~/.ssh/diski9_f3 deploy/f3/host/f3_day1_check.py root@<server IP>:/root/
```

Log in:

```bash
ssh -i ~/.ssh/diski9_f3 root@<server IP>
```

On the server, run:

```bash
python3 /root/f3_day1_check.py --target <pooler host>:5432 --target db.<ref>.supabase.co:5432 --json /root/f3-day1.json
```

The check is read-only:
* it measures TCP connection times only (no data, no login);
* it lists listening ports and the system facts;
* it masks public IP addresses.

**Return:** the full JSON output.

**G1:**
* **IT-1** PASS needs the **RTT p95 strictly below 10 ms** to every Supabase host, in
  every address family that **resolves** for it, with at least 95 % of samples
  succeeding. A family that resolves but never connects fails.
  * Each sample is one TCP handshake: no TLS, no login, no data.
  * 100 samples per host and family, 0.2 s apart (about 1–2 minutes in total).
  * Methodology: plan §Z.8.
  * IT-1 PASS is also the condition for final acceptance of the Düsseldorf VPS
    location.
* **IT-2** PASS needs a working IPv6 connection to the direct host. If IT-2 fails, the
  scheduler uses the session pooler, or the IPv4 add-on if the Checkpoint 3 lock test
  needs it. It is **not** a refund trigger on its own.
* A single IT-1 FAIL is repeated at a different time of day. FAIL on two different days
  is persistent: the DigitalOcean Frankfurt fallback applies (§X.4). Decide before
  day 25 (17 Dec 2026), inside the refund window and before the 22 Dec auto-renewal.

### O-6 Backblaze B2 (no payment until data is stored; first 10 GB free)

*Revised 22 Nov 2026: the web UI only offers a Compliance-mode default retention, so the
approved Governance 30-day default is set with the B2 CLI (plan §Y.6). Decisions A and B
are approved and C is conditionally approved. **Executing steps 2–5 needs a separate
explicit owner authorisation.***

1. **Account:**
   * Region **EU Central** chosen at sign-up (fixed for ever; Amsterdam).
   * **2FA on.** Card added. *(Done: 2FA on, EU Central.)*
2. **Create the bucket in the web UI. Irreversible: the name, and Object Lock being on.**
   * Name `diski9-f3-<8 hex>` (from `openssl rand -hex 4`).
   * **Private.**
   * Default encryption left as offered.
   * **Object Lock: Enable.**
   * **Do not set any default retention in the web UI** (it would be Compliance).
   * If the form insists on a retention period, stop and report; do not create the
     bucket.
   * Upload **nothing** until step 5 has passed: until then files are not locked.
3. **Lifecycle Settings → custom rules**, exactly:

   ```json
   [
     {"fileNamePrefix": "diski9/daily/",  "daysFromUploadingToHiding": 14, "daysFromHidingToDeleting": 30},
     {"fileNamePrefix": "diski9/weekly/", "daysFromUploadingToHiding": 56, "daysFromHidingToDeleting": 30},
     {"fileNamePrefix": "diski9/canary/", "daysFromUploadingToHiding": 1,  "daysFromHidingToDeleting": 30}
   ]
   ```

4. **Caps & Alerts:** daily caps on storage and Class A, B and C transactions (for
   example $0.10/day each; Class D cannot be capped).
5. **Set and prove Governance 30 days**, using the master key once.
   1. Install the CLI:

      ```bash
      brew install b2-tools
      ```

      `b2 version` should report 4.x or 5.x; 5.0.3 was verified.
   2. In the web UI: **App Keys → Generate New Master Application Key.** It is shown
      once. Keep the page open and do **not** save it anywhere.
   3. Run:

      ```bash
      deploy/f3/owner/f3-b2-configure-governance.sh diski9-f3-<suffix>
      ```

      * Paste the **keyID** at the script's hidden prompt.
      * Paste the **application key** at b2's hidden prompt ("Backblaze application
        key:").
      * Type `GOVERNANCE` to confirm.
   4. The script, step by step:
      * refuses keys in the environment;
      * keeps b2's login cache (which stores the key) on a RAM disk;
      * discards `b2 account authorize` output (it prints the key and token);
      * checks the bucket: private, Object Lock on, no Compliance default, approved
        lifecycle rules;
      * sets **governance / "30 days"**: the mode is fixed in the script; compliance
        is never used;
      * re-reads the bucket;
      * uploads one canary under `diski9/canary/`;
      * reads **that version** by file ID (`b2 file info b2id://<fileId>`), requiring
        mode `governance` and an expiry 30 days (± 1 hour) after upload;
      * prints sanitised evidence;
      * on **any** exit, including errors and Ctrl-C, runs `b2 account clear` and
        destroys the RAM disk.
      * On a failed step it prints only a fixed message naming the step; b2's raw
        response is never shown.
      * If the RAM disk cannot be removed, it prints **CLEANUP FAILED** with the exact
        removal command and exits with an error, even if everything else passed. Then
        remove the disk as instructed and rotate the master key at once (step 5).
   5. **Immediately afterwards**, whether the script passed or failed:
      * web UI → **Generate New Master Application Key** again. Backblaze: "Your master
        app key becomes invalid if you generate a new one", and "standard app keys
        continue to work even when the master app key is changed". Do not save the new
        one;
      * confirm that **no other application keys** exist;
      * close the Terminal window.
   6. **If the script, Terminal or the Mac was force-quit** (SIGKILL cannot be trapped,
      so cleanup did not run):
      * run `hdiutil info`;
      * find the entry whose mount point is `/Volumes/diski9f3<number>` and note its
        device (`/dev/diskN`);
      * run `hdiutil detach /dev/diskN -force`;
      * check that `ls /Volumes` no longer lists it.
      * A restart also discards a RAM disk.
      * Then do step 5. Regenerating the master key is the revocation that counts, even
        if the RAM disk is already gone.
      * Never run `b2 account get` (it prints the key), and never add `--verbose` or
        `--debug-logs`.
      * On Ctrl-C or a Terminal close, the script cleans up itself and stops.
6. **No other keys yet.**
   * The upload key, the list-only inventory key and the retrieval keys are created in
     Checkpoint 4, using the same one-time master-key procedure.
   * The inventory key gets `listBuckets`, `listFiles`, `readBucketRetentions` and
     `readFileRetentions` only.
   * **No operational key ever gets `bypassGovernance`.**

**Return:**
* the script's evidence block (`diski9-f3-b2-governance/1`): bucket name, type, Object
  Lock, default retention, lifecycle rules, canary retention and expiry;
* the cap values;
* "master key regenerated after use; no other keys exist".

#### O-6 incident (22 Nov 2026) and verify-only procedure — **O-6 stays open**

**What happened** (owner-reported, script at `5a9183e`, B2 CLI 5.0.3, bucket
`diski9-f3-3cd4db18`):
* authentication passed;
* the bucket checks passed;
* the 30-day Governance default was applied and re-verified (private, Object Lock,
  retention, lifecycle);
* `b2 file upload` returned success;
* the script then stopped: "the upload returned no usable file ID".
* The canary's retention was never read and no evidence block was produced.
* The owner rotated the master key afterwards.

**Confirmed cause:** B2 CLI 5.0.3's `file upload` prints `URL by file name: …` and
`URL by fileId: …` **before** its JSON (source `console_tool.py`, upload `_run`). The
script parsed the whole output as JSON. The test double printed JSON only, so the tests
missed it.

**Likely, not verified:**
* the canary was stored (the CLI prints those lines only after Backblaze accepted the
  upload);
* it is Governance-locked until about 30 days after upload (the verified bucket
  default applies at upload).

No credential was exposed: the URL lines went to the RAM-disk file, and they contain
only the download host, bucket name and file ID.

**Fix (`deploy/f3/owner/f3-b2-configure-governance.sh`):**
* the upload parser reads the JSON after the URL lines and requires the file ID in the
  `URL by fileId:` line to match the JSON's; otherwise it stops;
* new **`--verify-canary`** mode, which is **read-only**:
  * re-checks the bucket (private, Object Lock on, approved lifecycle, default
    retention already exactly Governance/30 days);
  * lists `diski9/canary/` with `b2 ls --json --versions -r`;
  * requires **exactly one uploaded** `setup-<UTC>.txt` version. Lifecycle **hide
    markers** for that same name, newer than the upload, are recognised and ignored;
    anything else (none, several uploads, other names or actions, a malformed listing)
    fails closed;
  * reads **that** version by file ID and requires Governance, an expiry of upload +
    30 days (± 1 hour) and no legal hold;
  * prints evidence `diski9-f3-b2-canary-verification/1`.
* It never uploads, updates the bucket, hides or deletes anything, and asks for no
  confirmation because it changes nothing.
* The same RAM-disk credential cache, discarded sign-in output, fixed failure messages,
  single cleanup path and CLEANUP FAILED rule apply.
* **Do not re-run the configure mode**: no second canary, no reapplied retention.

**Credential-free residue check** (run on the Mac at any time; prints counts or
presence only):
* expect `0`:

  ```bash
  ls /Volumes | grep -c '^diski9f3'
  ```

* expect `0`, unless you use other RAM disks:

  ```bash
  hdiutil info | grep -c 'ram://'
  ```

* expect `absent`:

  ```bash
  test -e ~/.b2_account_info && echo PRESENT || echo absent
  ```

* expect no output:

  ```bash
  ls -d ~/.config/b2 2>/dev/null
  ```

* expect `0`:

  ```bash
  env | grep -c '^B2_'
  ```

**Verify-only run** (needs separate explicit owner authorisation):
1. Update your clone to the reviewed commit and run the residue check above.
2. Web UI: **App Keys → Generate New Master Application Key** (shown once; not saved).
3. Run:

   ```bash
   deploy/f3/owner/f3-b2-configure-governance.sh --verify-canary diski9-f3-3cd4db18
   ```

   Paste the keyID at the script's hidden prompt and the key at b2's hidden prompt.
4. Immediately afterwards, whatever the result, generate a new master key again (not
   saved), confirm no other application keys exist, and close Terminal.
5. Run the residue check again.
6. **Return:** the evidence block (`diski9-f3-b2-canary-verification/1`), "master key
   rotated after use", and the residue-check results. If the script stops, return its
   message (it never contains b2 output).
7. O-6 closes only when the evidence shows the canary in **Governance** mode with an
   expiry about 30 days after its upload, and the evidence is recorded.

**Result: PASSED (2026-11-22, owner-run at `c332cd9`).** Sanitised evidence:

| Field | Value |
|---|---|
| Evidence schema | `diski9-f3-b2-canary-verification/1` |
| Verified at | 2026-11-22T18:38:03Z (repository HEAD `c332cd9`) |
| Bucket | `diski9-f3-3cd4db18`, `allPrivate`, Object Lock enabled |
| Default retention | Governance, 30 days |
| Lifecycle rules | all three approved rules matched |
| Canary | `diski9/canary/setup-20261122T174727Z.txt`, uploaded 2026-11-22T17:47:32Z |
| Canary retention | **Governance**, retain until **2026-12-22T17:47:32Z** (30.0 days); legal hold `null`; hide markers 0 |

Cleanup: master key rotated immediately; no Diski 9 RAM volume or attached RAM disk; no
B2 environment variables; no CLEANUP FAILED message. A pre-existing default B2 cache
(`~/.b2_account_info`, not used by the script) remains; deleting it is recommended. O-6
stays open for the monthly spending control (plan §Y.6, decisions S-1 to S-3).


### O-7 Peer devices (no cost)

Install the official WireGuard app on the laptop and the phone. Nothing else yet:
Checkpoint 2 generates each device's keys **on the device** and enrols it.

### Checkpoint 1 complete

Stop. Claude reviews the returned evidence against §8.2 and prepares Checkpoint 2.

## 5. Key handling and residual risks

### 5.1 The one-shot private CA (Checkpoint 2)

* **Server key:** the server's key is generated **on the VPS**
  (`deploy/f3/host/f3-make-server-csr.sh`) and never leaves it. Only the CSR (public)
  travels to the owner's computer.
* **CA key:** `deploy/f3/owner/f3-sign-server-cert.sh` creates the CA key **only in a RAM
  disk** (macOS: `hdiutil` RAM disk; Linux: tmpfs `/dev/shm`, refused if it is not
  tmpfs). The key exists for a few seconds:
  * the script signs exactly one certificate (`IP:10.88.0.1`, 180 days, no name
    constraints);
  * it overwrites and removes the key, then ejects or deletes the RAM disk.
* **Why not "delete the file":** on an SSD, deleting or overwriting a file does **not**
  guarantee erasure (wear levelling, TRIM, file-system copy-on-write, snapshots,
  backups). The key is therefore never written to persistent storage at all.

**Residual risks** (accepted for F3, documented):

| Risk | Mitigation | Remaining exposure |
|---|---|---|
| Memory pages swapped to disk while the key exists | macOS swap is encrypted. On Linux the script warns if swap is on; use encrypted swap or `swapoff -a` for the minute it runs | an unencrypted Linux swap could hold a copy |
| Hibernation/sleep image | do not sleep the computer during the run; FileVault encrypts the macOS sleep image | low |
| Malware or a backup/sync tool reading the RAM disk during those seconds | run on your own updated computer; the RAM disk is created fresh with a random name | a compromised computer defeats any local key handling |
| Memory remanence after ejection | not practically exploitable without physical access | negligible |
| The CA key leaked anyway | the root signs nothing further only if the key really is gone; trust is limited to your own devices and the private tunnel address; validity 180 days; the root is removed from every device at the end of F3 | an attacker would also need to be on the tunnel path to use it |

### 5.2 `age` identities

* The plaintext identity passes only through a pipe (memory) into `age -p` (scrypt
  passphrase encryption).
* At recovery time, `age -d -i <identity>.age` decrypts the identity in memory after
  asking for the passphrase.
* The same swap and malware residual risks apply, only for the duration of a
  generation or decryption.
* Losing one identity is survivable: every backup is encrypted to both.

### 5.3 Database credentials (Checkpoints 3–5)

* The `postgres` password stays with the owner. It is used **only from the owner's
  computer**:
  * to create the restricted backup role;
  * for M3 restores into drill projects;
  * for any task the restricted role is proven unable to do (§Y.3).
* It is not stored on the server unless IT-11 fails. In that case the isolated fallback
  of §Y.3 applies, and that is the owner's decision.

## 6. Backup completeness criteria (Checkpoints 4–5)

**A successful command exit is never evidence of a complete backup.** For each hosted
drill, Claude provides version-controlled, read-only verification scripts. The owner
runs them against **both** the live managed database and the restored drill project,
and returns both reports.

* **Frozen comparison point:** during a drill, the scheduler timer is stopped and no one
  signs in. Live and restored databases are then compared at the same logical point.
  The dump's own snapshot is used where `pg_dump` supports it.
* **Per-table evidence:**
  * row count;
  * an order-independent content hash (SHA-256 over rows sorted by primary key);
* **Tables covered:**
  * every table in Diski 9's `app` schema;
  * the Auth tables the backup must carry, at least `auth.users`, `auth.identities`,
    MFA factors if any, and the instance-level tables the data dump includes.
  * Volatile session and token tables (`auth.sessions`, `auth.refresh_tokens`) are
    compared by count only and reported. Signing in after a restore legitimately
    changes them.
* **Auth identity checks:**
  * every `auth.users` row has its `auth.identities` rows (provider `email`);
  * identity counts by provider match;
  * the owner's and the operator's user IDs, emails and confirmation timestamps match;
  * every Diski 9 account row references an existing `auth.users` ID.
* **Behavioural checks:**
  * an existing operator signs in to the restored environment;
  * `competition verify` is consistent;
  * migration head `app_0007`;
  * the provider hold is shown before cutover (§S.9).
* **Configuration:** the Auth settings are re-applied from the encrypted configuration
  export and compared item by item (Site URL, signups off, leaked-password protection,
  templates).
* **Restore-only scope:** objects outside the dump's scope (for example Storage objects,
  which Diski 9 does not use, and custom role passwords) are listed explicitly as
  restore-time steps, not silently assumed.

Any mismatch fails **G5**.

## 7. Password-manager entries (names only; values never leave the manager)

| Entry | Created in | Used where |
|---|---|---|
| Hostinger account (+ MFA recovery codes) | O-4 | hPanel |
| Hostinger VPS root password | O-4 | console break-glass only |
| SSH key passphrase (`diski9_f3`) | O-1 | owner's computer |
| Supabase account (+ MFA recovery codes) | O-3 | dashboard |
| Supabase postgres password | O-3 | owner's computer only (§5.3) |
| Backblaze account (+ MFA recovery codes) | O-6 | dashboard |
| age primary passphrase + attachment `diski9-f3-age-primary.age` | O-2 | recovery and drills |
| age offline passphrase (also on paper, apart from the medium) | O-2 | last-resort recovery |
| Diski 9 owner account (Supabase Auth user) | CP3 | the app |
| B2 upload key, B2 list-only key, drill retrieval keys | CP4 | server file / owner's computer / drill machine |
| Backup role password | CP4 | server file (root 0600) |
| Application secrets (`DISKI9_APP_SECRET_KEY`, token encryption key) | CP3 | server file (root 0600), generated on the server |

## 8. Verification checklists

### 8.1 Checkpoint 0 (Claude; this commit)
- [x] Owner sequence with every personal action, payment and secret identified (§4, §7).
- [x] Scripts version-controlled under `deploy/f3/`, tested end to end
  (`tests/test_f3_checkpoint0.py`):
  - one-shot CA issues exactly one IP-SAN certificate and leaves no key;
  - `age` identities are encrypted at rest and both decrypt;
  - the CSR script refuses to replace a key;
  - the day-one check is read-only and masks public IPs.
- [x] Key-handling residual risks documented (§5).
- [x] Completeness criteria for the Supabase backup defined (§6).
- [x] Hard-stop gates restated (§2).
- [x] F3-D7 references corrected to the WireGuard IP origin.
- [x] Checkpoint 1 preparation:
  - macOS prerequisites and a read-only checker (`f3-check-mac-prereqs.sh`);
  - scripts verified with age 1.1.1 and 1.3.2;
  - refusals added: LibreSSL refused, age older than 1.1 refused;
  - the day-one script reaches the server by `scp`, so no GitHub credentials are needed
    on the server.

### 8.2 Checkpoint 1 (owner evidence; Claude reviews)
- [x] O-1: SSH key fingerprint (received 22 Nov 2026; key login from the owner's Mac works).
- [x] O-2: two `age1…` recipients; both identities passed the round trip.
  **PASSED (22 Nov 2026): all criteria evidenced.**
  * Public recipients (bech32 checksums verified):
    * primary `age19sqxj3etzcl03gqzvcsn86p7v2xp8nheu4t2j6y9wpkd27ggyptqwkkty7`;
    * offline-recovery `age1vdhzrg30tplkq9ahcx2dkffynrshh8qkscjme3kself0jc63m5wqsssfrt`.
  * **PASSED: primary recovery test** (age and age-keygen v1.3.2):
    * a test message was encrypted to the primary recipient;
    * the passphrase-protected primary identity (stored in 1Password) was decrypted
      into a temporary 64 MB macOS RAM disk;
    * the recovered identity decrypted the test ciphertext to the exact expected
      plaintext;
    * the RAM disk was detached and the test file deleted; both cleanup checks
      succeeded.
  * **PASSED: offline custody and identity check:**
    * the encrypted offline identity is on the separate, approved recovery MacBook
      (FileVault on, stored securely, disconnected when not in use);
    * it was decrypted with its passphrase (age v1.3.2) and its format verified.
  * **PASSED: offline recovery round trip** (recovery MacBook, age v1.3.2):
    * a test message was encrypted to the offline recipient;
    * the passphrase-protected `diski9-f3-age-offline-recovery.age` was decrypted into a
      temporary 64 MB RAM disk;
    * the recovered identity decrypted the ciphertext to the exact expected plaintext;
    * the RAM disk was detached and the ciphertext deleted; cleanup checks "RAM DISK
      DETACHED" and "TEST FILE REMOVED".
  * Decrypting a real Diski 9 backup is still proven in the Checkpoint 5 drills.
- [x] O-3: Supabase Pro, spend cap on; project `diski9-f3` in `eu-central-1`, Micro; SSL
  enforcement on; signups off; leaked-password protection on; CA certificate saved;
  host names noted; no key shared. **PASSED (23 Nov 2026, owner-verified).**
  * organisation "Diski 9", **Pro**; project **`diski9-f3`**, `eu-central-1` (Frankfurt),
    Micro; project ref held by the owner (not recorded here, because it forms the
    direct host name; first and last characters `xswu…lfrf` only);
  * **spend cap on** (dashboard: usage limited to included quotas; the project may become
    unresponsive or read-only if they are exceeded);
  * **SSL enforcement on** (non-SSL connections rejected); **CA certificate** downloaded
    and saved by the owner for Checkpoint 3;
  * Auth: **new-user signup disabled**, manual linking disabled, anonymous sign-ins
    disabled, Confirm email enabled (22 Nov); **leaked-password protection on** (23 Nov);
  * project Auth TOTP capability enabled (separate from the dashboard account MFA);
  * **dashboard account MFA on** (authenticator app, confirmed in Account Settings →
    Security);
  * session-pooler and direct host names known to the owner (used in the day-one check;
    not recorded);
  * invoice EGXGMN-00001 (22 Nov 2026; period 22 Nov–21 Dec 2026): Pro **USD 25.00**,
    tax **USD 0.00**, total **USD 25.00**, PAID; a USD 0.00 invoice EGXGMN-00002, PAID.
    USD 25.00 is the verified subscription charge, **not** a ceiling on every possible
    Supabase charge; any reverse-charge tax obligation is unassessed;
  * the owner confirms that no database password, service-role/secret key, personal
    access token or other private credential was shared with ChatGPT, Claude, GitHub or
    anyone unauthorised.
- [x] O-4: Hostinger KVM 2, 1-month, Germany (provisioned in Düsseldorf: F3-D1a/F3-D2a
  conditionally approved, final on IT-1 PASS), Ubuntu 24.04, no add-ons; MFA on;
  SSH key login; console works; purchase date and day-25 reminder recorded; invoice
  amounts. **PASSED (23 Nov 2026), with SSH hardening explicitly deferred to
  Checkpoint 2.**
  * KVM 2 (2 vCPU / 8 GB / 100 GB), monthly, Ubuntu 24.04 LTS; data centre **Düsseldorf,
    Germany** as hPanel shows it. Final acceptance of the location (F3-D1a/F3-D2a) is
    tracked under O-5 (zero-success check), not here; it was met on 23 Nov 2026;
  * Hostinger account **two-factor authentication on**; **no add-ons purchased**;
  * console (IT-9) works; SSH key login works; host-key fingerprint recorded;
  * purchase date 22 Nov 2026 (refund day 0); first payment USD 12.64 incl. USD 1.65 tax;
  * **PASSED: day-25 refund-decision reminder:** calendar event "Hostinger VPS — Refund
    Decision", Thursday 17 Dec 2026, 09:00 SAST (UTC+02:00), to review suitability, cost
    and performance and decide whether to keep the VPS or request a refund before the
    expected 22 Dec 2026 deadline (screenshot seen by the owner). The deadline remains
    subject to Hostinger's actual terms and eligibility;
  * **SSH password authentication: currently ENABLED (verified, not changed).** Hostinger
    support confirmed (23 Nov 2026) that SSH currently permits password authentication,
    that an SSH key is configured for root, and that password authentication can be
    disabled in `sshd_config`. hPanel's "disable password login" was **not** used and
    **no SSH configuration change has been made**. The VPS is **not hardened**.
  * **Deviation (deferred, owner decision):** step 3's "if hPanel offers to disable
    password login, disable it" is not done; disabling it is deferred to Checkpoint 2
    VPS hardening. Before disabling it there, the owner must: confirm key-based login in
    a separate, still-open session; keep the hPanel browser console (IT-9) available;
    validate the effective configuration (`sshd -T`) before reloading; and avoid
    lockout. **Residual risk until then:** root password login is reachable on the
    public SSH port; it is mitigated only by the long random root password kept in the
    password manager. No application, data or credential is on the VPS yet.
- [x] O-5: day-one JSON (`diski9-f3-day1/2`): IT-1 PASS (RTT p95 < 10 ms); IT-2 PASS or
  the fallback path recorded; system facts (2 vCPU / 8 GB / ~100 GB). **PASSED (23 Nov
  2026), on the original 22 Nov 2026 JSON retrieved from the VPS by the owner.** Sanitised
  summary only; the raw JSON is **not** committed (it contains the full direct host name
  and project ref).
  * **IT-1 PASS** (every resolving family ≥ 95 % success and p95 < 10 ms):
    * session pooler IPv4: resolved, 100/100, p95 **5.730 ms**;
    * session pooler IPv6: **not resolved** (ignored; not a zero-success failure);
    * direct host IPv4: **not resolved** (ignored; not a zero-success failure);
    * direct host IPv6: resolved, 100/100, p95 **4.533 ms**.
  * **IT-2 PASS:** direct database host reachable over IPv6.
  * **IT-9:** JSON marks it MANUAL; owner-verified PASS (hPanel browser console).
  * **System facts:** Ubuntu 24.04.5 LTS, kernel 6.8.0-147-generic; 2 vCPU; 7.8 GiB
    memory; 95.8 GiB disk; NTP synchronised; IPv4 and IPv6 default routes present.
  * **Listening-port baseline (host view, not an external exposure test):** SSH TCP/22
    on IPv4 and IPv6; local DNS resolver TCP/UDP 53 on loopback only; no application
    listener.
  * **Zero-success check complete:** the two unreported families did not resolve, so the
    corrected §Z.8 rule gives the same PASS. The final-acceptance condition of
    F3-D1a/F3-D2a is met.
- [ ] O-6: B2 EU Central; bucket with Object Lock Governance 30 days; lifecycle rules;
  caps; **no keys created yet**.
  * **PASSED: canary verification** (2026-11-22T18:38:03Z, `--verify-canary`):
    `diski9-f3-3cd4db18` private, Object Lock on, default Governance 30 days, lifecycle
    rules matched; canary Governance until 2026-12-22T17:47:32Z (30.0 days), no legal
    hold, 0 hide markers.
  * **PASSED: credential cleanup:**
    * master key rotated immediately after the run;
    * no Diski 9 RAM volume and no attached RAM disk afterwards;
    * no B2 environment variables;
    * no CLEANUP FAILED message.
  * **OPEN:** monthly spending control (caps versus alerts; owner decisions S-1 to S-3
    in plan §Y.6).
  * **OPEN (hygiene):** a pre-existing default B2 cache `~/.b2_account_info` is
    present. The script never used it. Recommended: delete it without opening it
    (`rm ~/.b2_account_info`).
  * O-6 is **not closed** until these are resolved.
- [x] O-7: WireGuard app installed on both devices: the official client on the owner's
  MacBook and iPhone (22 Nov 2026). No tunnels configured. The WireGuard server and VPS
  hardening belong to Checkpoint 2 and are not authorised by this item.
- [ ] Running cost against the $65 alert and the $75 ceiling: **open**. The Supabase
  invoice is now verified (USD 25.00, tax USD 0.00; baseline in implementation record
  §13.9). The monthly control still needs owner decisions S-1 to S-3 (plan §Y.6).
