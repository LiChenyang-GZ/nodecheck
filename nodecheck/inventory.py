"""Step 1: read a node's hardware inventory from /proc and /sys.

Linux exposes hardware state as files: /proc for the kernel's own view (CPU, memory),
/sys for devices (disks, NICs, firmware tables). Commands like lscpu, free and lsblk
read the same files. Reading them directly needs no extra packages and no root.

`root` is where the filesystem starts: "/" on a real node, a fixture directory in tests.
Anything that can't be read becomes None (or is left out of a list); collect() never
crashes because one file is missing.
"""
from __future__ import annotations

from pathlib import Path

# /sys/block/<disk>/size is always counted in 512-byte sectors, whatever the disk's real sector size
SECTOR_BYTES = 512
# block devices that are not disks: loop = files mounted as disks (snaps), ram = RAM disks
SKIP_DISK_PREFIXES = ("loop", "ram")


def collect(root: Path | str = "/") -> dict:
    """Return the node's hardware inventory as a JSON-ready dict."""
    root = Path(root)
    return {
        "hostname": _read(root, "proc/sys/kernel/hostname"),
        "kernel": _read(root, "proc/sys/kernel/osrelease"),
        "os": _os_name(root),
        "system": {
            "vendor": _read(root, "sys/class/dmi/id/sys_vendor"),
            "product": _read(root, "sys/class/dmi/id/product_name"),
        },
        "cpu": _cpu(root),
        "memory": _memory(root),
        "disks": _disks(root),
        "nics": _nics(root),
    }


def _read(root: Path, relative: str) -> str | None:
    """Text of one file, stripped; None if it is missing or the kernel refuses to give it."""
    try:
        return (root / relative).read_text().strip()
    except (OSError, UnicodeDecodeError):
        # OSError covers "no such file" and also EINVAL, which e.g. .../net/eth0/speed
        # returns when the driver can't report a speed
        return None


def _int(text: str | None) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _os_name(root: Path) -> str | None:
    # /etc/os-release is KEY=value lines; PRETTY_NAME is the human-readable name
    text = _read(root, "etc/os-release")
    if text is None:
        return None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key == "PRETTY_NAME":
            return value.strip().strip('"')
    return None


def _cpu(root: Path) -> dict:
    # /proc/cpuinfo has one block per logical CPU, blocks separated by a blank line,
    # each line "key<TAB>: value"
    text = _read(root, "proc/cpuinfo")
    blocks = []
    for chunk in (text or "").split("\n\n"):
        fields = {}
        for line in chunk.splitlines():
            key, sep, value = line.partition(":")
            if sep:
                fields[key.strip()] = value.strip()
        if "processor" in fields:
            blocks.append(fields)

    if not blocks:
        return {"model": None, "logical_cpus": None, "physical_cores": None}

    # a physical core is one (socket, core) pair; hyperthreads share the pair
    cores = {(b.get("physical id"), b.get("core id")) for b in blocks}
    has_topology = all("core id" in b for b in blocks)
    return {
        "model": blocks[0].get("model name"),
        "logical_cpus": len(blocks),
        "physical_cores": len(cores) if has_topology else None,
    }


def _memory(root: Path) -> dict:
    # /proc/meminfo lines look like "MemTotal:   857080 kB"
    values = {}
    for line in (_read(root, "proc/meminfo") or "").splitlines():
        key, _, rest = line.partition(":")
        number = rest.split()[0] if rest.split() else None
        values[key] = _int(number)
    return {
        # what is installed and visible to the kernel: compared with the spec in step 2
        "total_kib": values.get("MemTotal"),
        # what new programs can still get, counting reclaimable cache; MemFree would
        # look tiny because Linux uses spare memory as cache
        "available_kib": values.get("MemAvailable"),
    }


def _disks(root: Path) -> list[dict]:
    base = root / "sys" / "block"
    if not base.is_dir():
        return []
    disks = []
    for device in sorted(base.iterdir(), key=lambda p: p.name):
        if device.name.startswith(SKIP_DISK_PREFIXES):
            continue
        rel = f"sys/block/{device.name}"
        sectors = _int(_read(root, f"{rel}/size"))
        rotational = _read(root, f"{rel}/queue/rotational")
        disks.append(
            {
                "name": device.name,
                "size_bytes": sectors * SECTOR_BYTES if sectors is not None else None,
                # 1 = spinning disk as reported by the driver; virtual disks often get this wrong
                "rotational": {"1": True, "0": False}.get(rotational),
                "vendor": _read(root, f"{rel}/device/vendor"),
                "model": _read(root, f"{rel}/device/model"),
            }
        )
    return disks


def _nics(root: Path) -> list[dict]:
    base = root / "sys" / "class" / "net"
    if not base.is_dir():
        return []
    nics = []
    for interface in sorted(base.iterdir(), key=lambda p: p.name):
        if interface.name == "lo":  # loopback: the machine talking to itself, not hardware
            continue
        rel = f"sys/class/net/{interface.name}"
        speed = _int(_read(root, f"{rel}/speed"))
        nics.append(
            {
                "name": interface.name,
                "mac": _read(root, f"{rel}/address"),
                "mtu": _int(_read(root, f"{rel}/mtu")),
                "state": _read(root, f"{rel}/operstate"),
                # Mbit/s as claimed by the driver; some drivers report -1 when unknown
                "speed_mbps": speed if speed is not None and speed > 0 else None,
            }
        )
    return nics
