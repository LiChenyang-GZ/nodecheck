# nodecheck

A small tool that validates Linux nodes before handover, modelled on how data-centre teams bring servers into service:

1. **Health check**: collect CPU, memory, disk, NIC, kernel-log and disk-usage state, and compare it to an expected spec (PASS / WARN / FAIL).
2. **Benchmark**: run `stress-ng`, `fio`, `iperf3` and `ping` (node to node), take the median of 3 runs, and store it as a baseline.
3. **Compare**: re-run and flag anything that got worse than the baseline.
4. **Fault drills**: inject faults (a bandwidth cap with `tc tbf`, added latency with `tc netem`, a full disk) and prove the tool catches them.
5. **Log bundle**: collect everything needed for an investigation with one command.

Test bed: two Ubuntu 24.04 VMs on Azure (Standard_B2ats_v2: 2 vCPU, 1 GiB) in the same subnet. How it was built: [`docs/learning/00-azure-test-bed.md`](docs/learning/00-azure-test-bed.md).

Python 3.10+, standard library only. Each step was built as `test(red)` → `feat`, with real command output from the VMs as test fixtures, and is explained in [`docs/learning/`](docs/learning/) (English + 中文).

## Commands

Run on the node itself; `--root DIR` reads a captured fixture directory instead of the live machine.

```bash
# hardware inventory as JSON
python3 -m nodecheck inventory

# health check against the machine type's spec; exit code 1 if anything FAILs
python3 -m nodecheck check --spec config/b2ats_v2.json

# benchmarks (about 4 minutes); the peer runs `iperf3 -s`
python3 -m nodecheck bench --spec config/b2ats_v2.json --peer 172.16.0.5 --out baselines/node-1.json

# run again and compare with this node's baseline; --only network takes about 45 s
python3 -m nodecheck compare --spec config/b2ats_v2.json --peer 172.16.0.5 --baseline baselines/node-1.json --only network

# collect the check report, logs and state into nodecheck-<host>-<time>.tar.gz
python3 -m nodecheck bundle --spec config/b2ats_v2.json --baseline baselines/node-1.json
```

Example (`check` on node-1 with the disk filled to 96%):

```
Spec: Azure Standard_B2ats_v2
  cpu         2 logical CPUs                     expected 2                                            PASS
  memory      0.82 GiB                           expected >= 0.80 GiB (1 GiB x 0.8)                    PASS
  disk        sda 64 GiB                         expected >= 64 GiB                                    PASS
  disk_type   not trusted here                   expected ssd (not verifiable on this platform)        WARN
  nics        1 up (eth0)                        expected >= 1 up                                      PASS
  os          Ubuntu 24.04.5 LTS                 expected Ubuntu 24.04*                                PASS
  kernel_log  0 errors (1 ignored, 10 warnings)  expected none at priority <= 3, boot 11 Nov 09:32 UTC PASS
  disk_usage  96% used (2.4 GiB free)            expected /: WARN from 80%, FAIL from 90%              FAIL
  inode_usage 1% used (8,166,108 free)           expected /: WARN from 80%, FAIL from 90%              PASS
Result: 1 FAIL, 1 WARN
```

## Fault drills

Each drill ran on node-1: the tool before the fault, during it, and after removing it.

| Fault | Injected with | Before | During | After |
|---|---|---|---|---|
| Bandwidth capped at 1 Gbit/s | `tc qdisc add dev eth0 root tbf rate 1gbit burst 256kb latency 50ms` | 5.73 Gbit/s PASS | **0.95 Gbit/s (−81%) FAIL**, exit 1 | 5.73 PASS |
| 2 ms added to every packet | `tc qdisc add dev eth0 root netem delay 2ms limit 10000` | 0.76 ms PASS | bandwidth 5.71 PASS, **latency 2.79 ms (+2.33 ms) FAIL**, exit 1 | 0.70 ms PASS |
| Root filesystem 96% full | `fallocate` | 4% PASS | **96% FAIL**, exit 1 | 4% PASS |

The latency drill found a real gap: the comparison judged bandwidth but only displayed latency, so 2 ms of extra delay passed with exit code 0. Write-up: [`docs/incidents/2026-11-11-added-latency.md`](docs/incidents/2026-11-11-added-latency.md).

## What the numbers mean on this test bed

- **Disk**: the OS disk has Azure host caching (ReadWrite), so `fio` measures ~9,400 IOPS on a disk rated at 3,500. Good for spotting drift, not a measure of the disk itself.
- **CPU**: B2ats_v2 is burstable (20% base). Benchmarks run while bursting; with no credits left the score drops to about a fifth.
- **Network**: one TCP stream gets 5–5.7 Gbit/s between the nodes; latency is about 0.5 ms and moves by tens of percent, so latency is judged in milliseconds, not as a percentage.

Each is recorded in the spec's and baseline's notes.

## Layout

```
nodecheck/        Python package (standard library only)
tests/            pytest tests
tests/fixtures/   real command output captured from the VMs, including under each fault
config/           expected spec per machine type (thresholds and their reasons)
baselines/        benchmark baseline per node
docs/learning/    one document per step (English + 中文)
docs/incidents/   fault drill write-ups
scripts/          helper for capturing fixtures
```

## Run the tests

```bash
python3 -m pytest
```
