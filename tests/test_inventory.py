"""Step 1: hardware inventory from /proc and /sys.

Fixtures in tests/fixtures/node-N/ are real copies of the kernel files, captured from the
Azure VMs with scripts/capture_fixture.sh. tests/fixtures/node-N/commands/ holds what
nproc, free, lsblk and uname printed at the same moment; the tests use them to check that
reading the files directly gives the same numbers as the usual commands.
"""
import json
from pathlib import Path

import pytest

from nodecheck.__main__ import main
from nodecheck.inventory import collect

FIXTURES = Path(__file__).parent / "fixtures"
NODE1 = FIXTURES / "node-1"


def command_output(node: Path, name: str) -> str:
    return (node / "commands" / name).read_text()


def test_cpu_model_and_counts_come_from_proc_cpuinfo():
    cpu = collect(NODE1)["cpu"]

    assert cpu["model"] == "AMD EPYC 7763 64-Core Processor"
    # Azure sells this size as "2 vCPU": the kernel sees 2 logical CPUs...
    assert cpu["logical_cpus"] == 2
    assert cpu["logical_cpus"] == int(command_output(NODE1, "nproc.txt"))
    # ...which are 1 physical core with 2 hardware threads (cpu cores: 1, siblings: 2).
    assert cpu["physical_cores"] == 1


def test_memory_reports_memtotal_and_memavailable_not_memfree():
    memory = collect(NODE1)["memory"]

    assert memory == {"total_kib": 857080, "available_kib": 594096}
    # `free -k` reads the same /proc/meminfo: its "total" column is MemTotal.
    free_total = int(command_output(NODE1, "free-k.txt").splitlines()[1].split()[1])
    assert memory["total_kib"] == free_total


def test_disks_come_from_sys_block_and_skip_loop_devices():
    disks = collect(NODE1)["disks"]

    assert disks == [
        {
            "name": "sda",
            # /sys/block/sda/size counts 512-byte sectors: 134217728 * 512 = 64 GiB
            "size_bytes": 68719476736,
            # an Azure Premium SSD, but the virtual disk reports rotational=1
            "rotational": True,
            "vendor": "Msft",
            "model": "Virtual Disk",
        }
    ]
    lsblk_size = int(command_output(NODE1, "lsblk.txt").splitlines()[1].split()[1])
    assert disks[0]["size_bytes"] == lsblk_size


def test_nics_come_from_sys_class_net_and_skip_loopback():
    nics = collect(NODE1)["nics"]

    assert nics == [
        {
            "name": "eth0",
            "mac": "60:45:bd:e5:04:a6",
            "mtu": 1500,
            "state": "up",
            # what the driver claims; the measured throughput was 4.84 Gbit/s
            "speed_mbps": 50000,
        }
    ]


@pytest.mark.parametrize("node", ["node-1", "node-2"])
def test_identity_hostname_kernel_os_and_system(node):
    root = FIXTURES / node
    inventory = collect(root)

    assert inventory["hostname"] == node
    assert inventory["kernel"] == "7.0.0-1017-azure"
    assert inventory["kernel"] == command_output(root, "uname-r.txt").strip()
    assert inventory["os"] == "Ubuntu 24.04.5 LTS"
    assert inventory["system"] == {"vendor": "Microsoft Corporation", "product": "Virtual Machine"}


def test_missing_or_unreadable_files_give_none_instead_of_crashing(tmp_path):
    # A node with almost nothing: one CPU, one NIC whose driver can't report a speed
    # (reading .../speed fails with "Invalid argument", so the capture skipped it),
    # and no DMI, meminfo, disks or os-release.
    (tmp_path / "proc").mkdir()
    (tmp_path / "proc" / "cpuinfo").write_text(
        "processor\t: 0\nmodel name\t: Test CPU\nphysical id\t: 0\ncore id\t: 0\n\n"
    )
    eth = tmp_path / "sys" / "class" / "net" / "eth0"
    eth.mkdir(parents=True)
    (eth / "address").write_text("00:11:22:33:44:55\n")
    (eth / "mtu").write_text("1500\n")
    (eth / "operstate").write_text("down\n")

    inventory = collect(tmp_path)

    assert inventory["cpu"] == {"model": "Test CPU", "logical_cpus": 1, "physical_cores": 1}
    assert inventory["nics"] == [
        {"name": "eth0", "mac": "00:11:22:33:44:55", "mtu": 1500, "state": "down", "speed_mbps": None}
    ]
    assert inventory["memory"] == {"total_kib": None, "available_kib": None}
    assert inventory["disks"] == []
    assert inventory["os"] is None
    assert inventory["system"] == {"vendor": None, "product": None}


def test_cli_inventory_prints_json(capsys):
    exit_code = main(["inventory", "--root", str(NODE1)])

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == collect(NODE1)
    assert printed["cpu"]["logical_cpus"] == 2
