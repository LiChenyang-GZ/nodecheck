# nodecheck

A small tool that validates Linux nodes before handover, modelled on how data-centre teams bring servers into service:

1. **Health check**: collect CPU, memory, disk, NIC and kernel-log state, and compare it to an expected spec (PASS / WARN / FAIL).
2. **Benchmark**: run `stress-ng`, `fio` and `iperf3` (node to node), take the median of 3 runs, and store it as a baseline.
3. **Compare**: re-run and flag anything that drifts too far from the baseline.
4. **Fault drills**: inject faults (bandwidth limit and latency with `tc netem`, a full disk) and prove the tool catches them.
5. **Log bundle**: collect everything needed for an investigation with one command.

Test bed: two Ubuntu 24.04 VMs on Azure (Standard_B2ats_v2: 2 vCPU, 1 GiB) in the same subnet. How it was built: [`docs/learning/00-azure-test-bed.md`](docs/learning/00-azure-test-bed.md).

> Status: work in progress. Each step is committed as `test(red)` → `feat`, and explained in [`docs/learning/`](docs/learning/).

## Layout

```
nodecheck/        Python package (standard library only)
tests/            pytest tests
tests/fixtures/   real command output captured from the VMs
config/           expected spec per node type
docs/learning/    one document per step (English + 中文)
```

## Run the tests

```bash
python3 -m pytest
```
