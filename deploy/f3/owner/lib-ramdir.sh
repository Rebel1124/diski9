# shellcheck shell=bash
# Diski 9 Stage F3: a memory-backed scratch directory for short-lived private keys.
# Sourced by the owner scripts; never run directly.
#
# Why: a deleted file on an SSD is not reliably erased (wear levelling, TRIM, snapshots),
# so private keys that must not survive (the one-shot CA key) are only ever written to
# RAM: a RAM disk on macOS, tmpfs (/dev/shm) on Linux. Residual risks that remain are
# documented in docs/operations_f3_owner_setup.md (swap, hibernation images, malware
# running while the key exists).

F3_RAMDIR=""
F3_RAMDEV=""

f3_die() { echo "error: $*" >&2; exit 1; }

f3_ramdir_create() {
  local tag="diski9f3$$" out
  F3_RAMDIR=""
  F3_RAMDEV=""
  # Install cleanup BEFORE anything is created, so a failure or a signal at any point
  # of initialisation (attach, format, mktemp, chmod) cannot leave a RAM disk behind.
  # Signals become an exit (the EXIT trap then cleans up); the script never continues.
  # Callers may replace these traps afterwards with their own single cleanup path.
  trap f3_ramdir_destroy EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
  case "$(uname -s)" in
    Darwin)
      # 64 MiB RAM disk (512-byte sectors); never backed by the SSD
      out=$(hdiutil attach -nomount ram://131072) || f3_die "could not create a RAM disk"
      F3_RAMDEV=$(printf '%s\n' "$out" | awk 'NR == 1 {print $1}')
      case "$F3_RAMDEV" in
        /dev/disk[0-9]*) ;;
        *)
          F3_RAMDEV=""
          f3_die "unexpected hdiutil output; check 'hdiutil info' for a stray RAM disk and detach it"
          ;;
      esac
      # from here on the device is recorded, so any failure detaches it
      diskutil erasevolume HFS+ "$tag" "$F3_RAMDEV" >/dev/null || f3_die "could not format the RAM disk"
      F3_RAMDIR="/Volumes/$tag"
      ;;
    Linux)
      local fs
      fs=$(stat -f -c %T /dev/shm 2>/dev/null || true)
      [ "$fs" = "tmpfs" ] || f3_die "/dev/shm is not tmpfs ($fs): refusing to write private keys to disk"
      F3_RAMDIR=$(mktemp -d /dev/shm/diski9-f3.XXXXXX) || f3_die "could not create a tmpfs directory"
      if [ -n "$(swapon --noheadings 2>/dev/null || true)" ]; then
        echo "warning: swap is enabled; tmpfs pages can be swapped to disk (residual risk, see runbook)" >&2
      fi
      ;;
    *) f3_die "unsupported operating system: use macOS or Linux" ;;
  esac
  [ -d "$F3_RAMDIR" ] || f3_die "the RAM disk is not mounted at $F3_RAMDIR"
  chmod 700 "$F3_RAMDIR" || f3_die "could not restrict the RAM disk's permissions"
}

# Returns 1 (and keeps the location in F3_RAMDIR_LEFT / F3_RAMDEV_LEFT) if the RAM
# disk or directory is still present afterwards. Never aborts part-way (safe under set -e
# and inside traps): every step is attempted, then the result is checked.
F3_RAMDIR_LEFT=""
F3_RAMDEV_LEFT=""
f3_ramdir_destroy() {
  # handles partial initialisation too: a device attached but not yet formatted
  # (no directory recorded) is still detached
  [ -n "$F3_RAMDIR$F3_RAMDEV" ] || return 0
  local dir=$F3_RAMDIR dev=$F3_RAMDEV failed=0
  if [ -n "$dir" ] && [ -d "$dir" ]; then
    # overwrite in place (meaningful for RAM-backed files), then remove
    find "$dir" -type f -exec sh -c 'for f; do
      n=$(wc -c < "$f" | tr -d " "); dd if=/dev/zero of="$f" bs=1 count="$n" conv=notrunc 2>/dev/null; rm -f "$f"; done' sh {} + 2>/dev/null || true
  fi
  if [ -n "$dev" ]; then
    hdiutil detach "$dev" -force >/dev/null 2>&1 || failed=1  # removes the mount point too
  elif [ -n "$dir" ]; then
    rm -rf "$dir" 2>/dev/null || true
  fi
  if [ -n "$dir" ] && [ -e "$dir" ]; then failed=1; fi
  F3_RAMDIR=""
  F3_RAMDEV=""
  if [ "$failed" -ne 0 ]; then
    F3_RAMDIR_LEFT=$dir
    F3_RAMDEV_LEFT=$dev
    echo "WARNING: the temporary RAM disk could not be removed: ${dir:-(not mounted)}${dev:+ (device $dev)}." >&2
    echo "         Remove it now: ${dev:+hdiutil detach $dev -force}${dev:-rm -rf $dir}" >&2
    return 1
  fi
  return 0
}
