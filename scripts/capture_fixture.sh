#!/usr/bin/env bash
# Capture the kernel files nodecheck reads, as plain files, so tests can run on real data anywhere.
#
# Usage (on a node):  bash capture_fixture.sh node-1
# Output:             /tmp/node-1-fixture.tar.gz
#   node-1/proc/...      copies of /proc files
#   node-1/sys/...       copies of /sys files
#   node-1/etc/os-release
#   node-1/commands/*.txt  output of lscpu, free, lsblk, ip... for cross-checking
#
# Why `cat` and not `cp` or `tar`: files under /proc and /sys report size 0.
# The kernel generates their content only when you read them, so tar would archive empty files.
set -euo pipefail

name="${1:-$(hostname)}"
work="/tmp/nodecheck-fixture"
out="$work/$name"
rm -rf "$out"
mkdir -p "$out/commands"

# copy one pseudo-file as a regular file; skip it if it cannot be read
# (for example /sys/class/net/lo/speed returns "Invalid argument")
copy() {
  local src="$1"
  [ -e "$src" ] || return 0
  mkdir -p "$out$(dirname "$src")"
  if ! cat "$src" > "$out$src" 2>/dev/null; then
    rm -f "$out$src"
  fi
}

# CPU, memory, kernel, hostname, OS
for f in /proc/cpuinfo /proc/meminfo /proc/sys/kernel/osrelease /proc/sys/kernel/hostname /etc/os-release; do
  copy "$f"
done

# system / BIOS identity (world-readable part of DMI; serials need root, so we skip them)
for f in sys_vendor product_name bios_vendor bios_version; do
  copy "/sys/class/dmi/id/$f"
done

# block devices
for d in /sys/block/*; do
  for f in size removable ro queue/rotational device/model device/vendor; do
    copy "$d/$f"
  done
done

# network interfaces
for d in /sys/class/net/*; do
  for f in address mtu operstate speed type; do
    copy "$d/$f"
  done
done

# the same information as the usual commands show it, to cross-check our parsing
run() { local file="$1"; shift; "$@" > "$out/commands/$file" 2>&1 || true; }
run nproc.txt   nproc
run lscpu.txt   lscpu
run free-k.txt  free -k
run lsblk.txt   lsblk -b -d -o NAME,SIZE,ROTA,TYPE,MODEL
run ip-link.txt ip -br link
run uname-r.txt uname -r

tar czf "/tmp/$name-fixture.tar.gz" -C "$work" "$name"
echo "wrote /tmp/$name-fixture.tar.gz ($(find "$out" -type f | wc -l) files)"
