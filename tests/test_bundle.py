"""One command collects what an investigation needs into a .tar.gz.

Commands are answered by a fake runner, so no VM is needed; the health check report and
the inventory come from node-1's fixture (--root), like the other check tests.
"""
import json
import tarfile
from pathlib import Path

from nodecheck import bundle
from nodecheck.__main__ import main

ROOT = Path(__file__).parent.parent
NODE1 = ROOT / "tests" / "fixtures" / "node-1"
SPEC_FILE = ROOT / "config" / "b2ats_v2.json"
BASELINE_FILE = ROOT / "baselines" / "node-1.json"
COPIES = {"spec.json": SPEC_FILE, "baseline.json": BASELINE_FILE}


def fake_runner(broken=(), missing=()):
    """Every command prints a line naming itself; `broken` ones exit 1, `missing` ones don't exist."""
    def runner(command):
        line = " ".join(command)
        if any(m in line for m in missing):
            return None, ""
        if any(b in line for b in broken):
            return 1, f"{command[0]}: something went wrong\n"
        return 0, f"output of {line}\n"
    return runner


def members(path):
    """{name inside the top folder: text} of a .tar.gz ({} if there is none)."""
    if not Path(path).exists():
        return {}
    with tarfile.open(path, "r:gz") as tar:
        out = {}
        for m in tar.getmembers():
            if m.isfile():
                out[m.name.split("/", 1)[1]] = tar.extractfile(m).read().decode()
        return out


def top_folders(path):
    if not Path(path).exists():
        return set()
    with tarfile.open(path, "r:gz") as tar:
        return {m.name.split("/", 1)[0] for m in tar.getmembers()}


def manifest(files):
    """{file: (exit, bytes, command)} from MANIFEST.txt (tab-separated, header first)."""
    rows = {}
    for line in files.get("MANIFEST.txt", "").splitlines()[1:]:
        name, code, size, command = line.split("\t")
        rows[name] = (code, int(size), command)
    return rows


def make(tmp_path, runner):
    out = tmp_path / "nodecheck-node-1-test.tar.gz"
    return bundle.make(out, report="Result: 0 FAIL, 1 WARN\n", inventory={"hostname": "node-1"},
                       copies=COPIES, root=NODE1, runner=runner)


def test_bundle_holds_every_command_the_report_and_a_manifest(tmp_path):
    path = make(tmp_path, fake_runner())

    assert path.exists()
    assert top_folders(path) == {"nodecheck-node-1-test"}  # unpacks into one folder
    files = members(path)
    for name, command in bundle.COMMANDS.items():
        assert files.get(name) == f"output of {' '.join(command)}\n", name
    assert files.get("check.txt") == "Result: 0 FAIL, 1 WARN\n"
    assert json.loads(files.get("inventory.json", "{}")) == {"hostname": "node-1"}
    assert files.get("os-release") == (NODE1 / "etc" / "os-release").read_text()


def test_tc_state_is_collected(tmp_path):
    # a forgotten tc rule (like the drills' tbf or netem) looks exactly like a slow network
    assert "tc-qdisc.txt" in bundle.COMMANDS
    assert "tc-qdisc.txt" in members(make(tmp_path, fake_runner()))


def test_spec_and_baseline_are_copied_as_they_are(tmp_path):
    files = members(make(tmp_path, fake_runner()))

    assert files.get("spec.json") == SPEC_FILE.read_text()
    assert files.get("baseline.json") == BASELINE_FILE.read_text()


def test_a_failing_command_is_recorded_and_the_rest_still_collected(tmp_path):
    files = members(make(tmp_path, fake_runner(broken=["journalctl -p err"])))
    rows = manifest(files)

    assert rows.get("journalctl-err.txt", ("",))[0] == "1"
    assert "something went wrong" in files.get("journalctl-err.txt", "")  # its output is kept too
    assert rows.get("df.txt", ("",))[0] == "0"
    assert "df.txt" in files


def test_a_missing_tool_is_recorded_as_not_found(tmp_path):
    rows = manifest(members(make(tmp_path, fake_runner(missing=["tc qdisc"]))))

    assert rows.get("tc-qdisc.txt", ("", 1))[:2] == ("not found", 0)


def test_manifest_lists_every_file_with_its_size(tmp_path):
    files = members(make(tmp_path, fake_runner()))
    rows = manifest(files)

    assert set(rows) == set(files) - {"MANIFEST.txt"}
    for name, (code, size, command) in rows.items():
        assert size == len(files[name].encode()), name
    assert rows.get("uname.txt", ("", 0, ""))[2] == "uname -a"


def test_bundle_holds_nothing_but_the_listed_files(tmp_path):
    # a fixed list: no keys, no shadow file, nothing picked up by accident
    expected = set(bundle.COMMANDS) | set(bundle.FILES) | set(COPIES) | {"check.txt", "inventory.json", "MANIFEST.txt"}

    files = members(make(tmp_path, fake_runner()))

    assert set(files) == expected


def test_cli_bundle_writes_the_archive_with_the_check_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bundle, "run", fake_runner())
    out = tmp_path / "b.tar.gz"
    main(["check", "--spec", str(SPEC_FILE), "--root", str(NODE1)])
    report = capsys.readouterr().out

    code = main(["bundle", "--spec", str(SPEC_FILE), "--baseline", str(BASELINE_FILE),
                 "--root", str(NODE1), "--out", str(out)])
    printed = capsys.readouterr().out

    assert code == 0
    assert out.exists() and str(out) in printed
    files = members(out)
    assert files.get("check.txt") == report  # the same report `check` prints
    assert json.loads(files.get("inventory.json", "{}")).get("hostname") == "node-1"
    assert files.get("baseline.json") == BASELINE_FILE.read_text()


def test_cli_bundle_default_name_has_host_and_time(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bundle, "run", fake_runner())
    monkeypatch.chdir(tmp_path)

    main(["bundle", "--spec", str(SPEC_FILE), "--root", str(NODE1)])

    made = list(tmp_path.glob("nodecheck-*-*.tar.gz"))
    assert len(made) == 1
