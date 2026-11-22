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
  local tag="diski9f3$$"
  case "$(uname -s)" in
    Darwin)
      # 64 MiB RAM disk (512-byte sectors); never backed by the SSD
      F3_RAMDEV=$(hdiutil attach -nomount ram://131072 | awk '{print $1}')
      [ -n "$F3_RAMDEV" ] || f3_die "could not create a RAM disk"
      diskutil erasevolume HFS+ "$tag" "$F3_RAMDEV" >/dev/null || f3_die "could not format the RAM disk"
      F3_RAMDIR="/Volumes/$tag"
      ;;
    Linux)
      local fs
      fs=$(stat -f -c %T /dev/shm 2>/dev/null || true)
      [ "$fs" = "tmpfs" ] || f3_die "/dev/shm is not tmpfs ($fs): refusing to write private keys to disk"
      F3_RAMDIR=$(mktemp -d /dev/shm/diski9-f3.XXXXXX)
      if [ -n "$(swapon --noheadings 2>/dev/null || true)" ]; then
        echo "warning: swap is enabled; tmpfs pages can be swapped to disk (residual risk, see runbook)" >&2
      fi
      ;;
    *) f3_die "unsupported operating system: use macOS or Linux" ;;
  esac
  chmod 700 "$F3_RAMDIR"
  trap f3_ramdir_destroy EXIT INT TERM
}

f3_ramdir_destroy() {
  [ -n "$F3_RAMDIR" ] || return 0
  if [ -d "$F3_RAMDIR" ]; then
    # overwrite in place (meaningful for RAM-backed files), then remove
    find "$F3_RAMDIR" -type f -exec sh -c 'for f; do
      n=$(wc -c < "$f"); dd if=/dev/zero of="$f" bs=1 count="$n" conv=notrunc 2>/dev/null; rm -f "$f"; done' sh {} +
    rm -rf "$F3_RAMDIR"
  fi
  if [ -n "$F3_RAMDEV" ]; then
    hdiutil detach "$F3_RAMDEV" -force >/dev/null 2>&1 || echo "warning: eject $F3_RAMDEV manually" >&2
  fi
  F3_RAMDIR=""
  F3_RAMDEV=""
}
