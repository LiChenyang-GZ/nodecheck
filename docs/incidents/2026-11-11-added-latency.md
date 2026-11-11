# Fault drill write-up: 2 ms of added latency passed the comparison

[中文](2026-11-11-added-latency.zh-CN.md)

> **This was a planned fault drill on a test bed, not a production incident.** It is written up in the blameless postmortem format, because the drill found a real gap in the tool. Times are AEDT (UTC+11), 11 Nov 2026.

## Summary

`nodecheck compare` checks a node's benchmarks against its own baseline. With 2 ms of delay added to every packet node-1 sent, bandwidth stayed at 5.65 Gbit/s and the comparison passed with exit code 0, although every round trip took 2.36 ms longer (0.46 → 2.82 ms). The comparison judged bandwidth but only displayed latency. We added a latency check measured in milliseconds above the baseline; the same fault now fails with exit code 1.

## Impact

- On the test bed: none; the fault was injected on purpose and removed straight after.
- What it would have meant: a node with a 6× slower network round trip would have been accepted. Inside a data centre a round trip is usually well under a millisecond, and jobs that exchange results between nodes at every step (distributed training, for example) slow down while every bandwidth test passes.

## Detection

By the drill itself: the comparison's output showed latency at +509% marked INFO ("not judged"), with `Result: 0 FAIL, 0 WARN`.

## Timeline

| Time | What happened |
|---|---|
| 18:12 | Baseline measured on node-1: 5.03 Gbit/s, 0.463 ms (median of 3) |
| 21:04 | Previous drill (tbf, bandwidth capped at 1 Gbit/s) caught: −81%, FAIL, exit 1 |
| ~21:10 | Trial of 2, 5 and 10 ms of netem delay. Only 2 ms left bandwidth unchanged (5.65 Gbit/s); 5 ms cut it by 25%, 10 ms by 56% |
| 21:16 | Output captured under `netem delay 2ms limit 10000` as a test fixture |
| ~21:18 | Same fixture through `compare`: bandwidth PASS, latency INFO, exit 0. **Gap confirmed** |
| 21:19 | Failing tests committed (`5fb430e`): latency must FAIL at +2.36 ms and stay PASS for everyday noise |
| 21:22 | Fix in place; drill on node-1: before PASS → delay 2.79 ms (+2.33 ms) FAIL, exit 1 → after PASS |
| 21:24 | Fix committed (`9e2fd02`) |

(Times come from the captured files and the commits; "~" marks ones estimated from the order of work.)

## Root cause

1. **Only one network metric was judged.** The comparison was built around bandwidth, the metric the first drill (a bandwidth cap) exercised. Latency was measured and shown, but had no thresholds, so it couldn't fail.
2. **Latency had been left out on purpose, for a reason that still needed a design.** A percentage threshold doesn't work for a 0.46 ms baseline: on the same evening, with no fault, latency was up to 0.64 ms higher (+139%). A 25% rule would have failed almost every run.

## Resolution

Thresholds can now be given in the metric's own unit (`warn_by` / `fail_by`) as well as a share of the baseline (`warn_drop` / `fail_drop`). Latency: WARN at +1 ms, FAIL at +1.5 ms above the baseline: above all the noise seen (+0.64 ms), below the fault (+2.33 ms). The report shows latency as `+2.36 ms` rather than `+509%`.

## What went well

- The trial before the drill: picking 5 ms, as first planned, would have cut bandwidth too, and the bandwidth check would have caught it, hiding the gap.
- Real output as fixtures: the failing test used the exact numbers from the VM.
- Raising netem's queue limit (`limit 10000`): with the default, 5 ms of delay also dropped packets (3.46 vs 3.78 Gbit/s), mixing loss into a latency test.

## What went wrong

- An earlier reading was misread: at 20:44, ping averaged 1.105 ms under the bandwidth cap, and it looked like the cap had raised latency. A control measurement at 21:04 (0.68 ms during the cap, 0.71 and 0.84 ms around it) showed it was time-of-day noise.
- The baseline is ageing: latency without a fault now sits at 0.7–1.0 ms against a 0.463 ms baseline.

## Action items

| Item | Status |
|---|---|
| Latency judged in ms above the baseline | Done (`9e2fd02`) |
| `bundle` collects `tc qdisc show`, so a forgotten tc rule is visible in an investigation | Done (step 8) |
| Re-measure the baseline, or keep several and compare with a range | Open |
| Consider the per-packet median of ping instead of the average (more robust to spikes; needs a new baseline) | Open |
| Run the drills on node-2 as well (only node-1 so far) | Open |

## Lessons

- **Bandwidth and latency fail independently.** A check that measures one says nothing about the other.
- **Pick each threshold in the unit where normal noise is small compared with the faults you care about.** For bandwidth that's a percentage; for a sub-millisecond latency it's milliseconds.
- **Don't trust a check until you've seen it fail**, and make sure the drill fails it for the right reason.
