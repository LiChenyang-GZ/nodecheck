# 07 · Fault drill 3: a big enough disk can still be full

[中文](07-disk-full.zh-CN.md)

> Step type: **fault drill**. Fill the disk, show the health check doesn't notice (red), add a usage check (green), prove it before, during and after.

## 1. The problem

The spec check asks whether the disk is **big enough** (at least 64 GiB). It never asks how much is **left**. A node whose disk is 96% full passes, and the first job that writes checkpoints or logs fails, often without even being able to log why.

The fault, on node-1, as an ordinary user:

```
fill=$(df -P -B1 / | awk 'NR==2{print int(($3+$4)*0.96-$3)}')   # bytes needed to reach 96%
fallocate -l $fill /var/tmp/nodecheck-fill                       # inject: instant, no data written
rm -f /var/tmp/nodecheck-fill                                    # restore
```

Reproduced by `tests/test_disk_usage.py` (11 cases). Fixtures are node-1's real `df` output: `tests/fixtures/node-1/commands/df.txt` and `df-i.txt` (normal), `tests/fixtures/node-1/fault-disk/df.txt` (after `fallocate` took 60 GB) and `df-after.txt` (after it was deleted). While `disk_usage.py` was a stub that didn't look, 9 cases failed on assertions.

Drill on node-1 (`check`, live, no `--root`):

| | `disk_usage` | `inode_usage` | Exit |
|---|---|---|---|
| before | 4% used (58.5 GiB free) PASS | 1% PASS | 0 |
| **96% full** | **96% used (2.4 GiB free) FAIL** | 1% PASS | **1** |
| after | 4% used (58.5 GiB free) PASS | 1% PASS | 0 |

## 2. What it is

**Reading `df -P -B1 /`**

```
Filesystem        1-blocks        Used  Available Capacity Mounted on
/dev/root      65445814272 62811885568 2617151488      97% /
```

| Column | Meaning |
|---|---|
| 1-blocks | total size in 1-byte blocks (`-B1`): 61 GiB here, on a 64 GiB disk (partitions and filesystem metadata take the rest) |
| Used / Available | used, and what an **ordinary user** can still use |
| Capacity | used ÷ (used + available), **rounded up**: 96.0% prints as 97% |

`-P` (POSIX format) keeps each filesystem on one line, so it's safe to parse.

**Two ways to run out**

| Resource | What it is | How it runs out |
|---|---|---|
| space | bytes | one huge file, logs that are never rotated, checkpoints |
| inodes | one per file or directory, holding its metadata (size, owner, where the data is); the count is fixed when the filesystem is created | millions of tiny files (caches, mail queues): `df` shows plenty of space, yet no new file can be created |

This disk has 8,257,536 inodes, 91,417 in use. The 60 GB file used one.

**Reserved blocks**: ext4 usually keeps 5% for root, so root can still log in and clean up when users have filled the disk. Here total − used − available = **16 MiB**: this image reserves almost nothing, so an ordinary user can fill the disk to 100%. The drill stops at 96% and deletes the file straight away.

**`fallocate` vs `dd`**: `fallocate` asks the filesystem to reserve the blocks without writing them: instant, and no disk burst credits spent. `dd` would actually write 60 GB.

| Code | What it does |
|---|---|
| `disk_usage#read` | runs `df -P -B1 <mount>` and `df -P -i <mount>`; with `--root`, reads `commands/df.txt` and `df-i.txt` |
| `disk_usage#parse` | total, used, available and the exact used share from the first filesystem line; anything else → `None` |
| `disk_usage#check` | `disk_usage` and `inode_usage`: ≥ 90% FAIL, ≥ 80% WARN, unreadable WARN |
| `__main__#main` (`check`) | adds the two results after the kernel log; the mount comes from the spec |

## 3. Code path

```mermaid
sequenceDiagram
    participant U as "python3 -m nodecheck check"
    participant M as "__main__#main"
    participant D as "disk_usage"
    U->>M: --spec [--root DIR]
    M->>M: spec checks, kernel log (as before)
    M->>D: read(root, spec.disk_usage.mount)
    D-->>M: df text, df -i text (or None)
    M->>D: parse each, then check(space, inodes, spec)
    D-->>M: disk_usage, inode_usage results
    M-->>U: report; exit 1 if any FAIL
```

## 4. Why this way

| Choice | Why | Alternative and cost |
|---|---|---|
| 🤖 parse `df` output | same numbers an engineer sees; the real output becomes a fixture and `--root` tests it anywhere | `os.statvfs`: no subprocess, but nothing real to capture as a fixture |
| 🤖 WARN 80%, FAIL 90% | common alerting levels; leaves room to act before 100% | one level: either too late or too noisy |
| 🤖 exact share, not df's rounded one | 96.0% is 96%; rounding up would turn 89.1% into a FAIL | use df's column: simpler, sometimes one step harsher |
| 🤖 inodes checked, same thresholds | running out of inodes looks like a full disk to programs, while `df` shows free space | space only: misses the classic small-files failure |
| 🤖 inode exhaustion tested on an edited fixture | 8.26 million files would take long to create on the VM | a real drill: slow, little extra learning |
| 🤖 `fallocate`, stop at 96% | instant; there's almost no root reserve here, so going to 100% could break logins or logging | `dd`: real writes, slow, burns burst credits |
| 🤖 unreadable `df` → WARN | not seen isn't fine | PASS: a missing check looks like a healthy disk |

## 5. Interview topics here

**Conclusion**: "big enough" and "has room" are different checks; and there are two things to run out of.

| Topic | Code | Judgement here |
|---|---|---|
| 📗 TS-RS29 what is an inode | `inode_usage` | one per file; fixed at creation; 8.26 million here |
| 📗 TS-SS17 what's in an inode | — | metadata: size, owner, permissions, timestamps, block pointers; **not the name** (that's in the directory) |
| 📗 TS-SS45 `df` and `du` disagree | not in the code | a deleted file still held open by a process: `du` can't see it, `df` still counts it until the process closes it. Fix: find it with `lsof +L1`, restart or truncate. **When it doesn't apply**: our drill deletes a file nobody holds open, so space came back at once |
| 📗 TS-JS29 find big files | follow-up after a FAIL | `du -xh / | sort -h | tail`, or `find / -xdev -size +1G` |
| 📗 TS-SS14 delete 100 GB of files | — | many small files: `find -delete` or `rsync --delete` from an empty dir rather than `rm *` (argument list too long) |
| ➕ df rounds up | `parse` | 96.0% prints as 97% |
| ➕ reserved blocks | spec note | usually 5% for root; 16 MiB on this image |

Scenario anchors:
- "The health check only verified the disk was big enough. I filled it to 96% with fallocate, added a usage check for space and inodes, and the drill failed with exit code 1, then passed after cleanup."
- "I noticed this image reserves only 16 MB for root instead of the usual 5%, so a user process can fill the disk completely."

## 6. Follow-up chain

1. **A server's disk is full. What do you check?** `df -h` for space, `df -i` for inodes, then `du` to find what's big; if `df` and `du` disagree, look for deleted files held open (`lsof +L1`).
2. **What is an inode?** The record of one file's metadata; the count is fixed when the filesystem is made.
3. **How can a disk be "full" with space free?** No inodes left: millions of small files.
4. **Why does root still manage to write when users can't?** Reserved blocks (`tune2fs -m`), usually 5%. Not on this image, though: 16 MiB.
5. **How did you test it without writing 60 GB?** `fallocate` reserves the blocks without writing data.

## 7. How to say it

- "Big enough and has room are two different checks."
- "A disk can be full in two ways: out of space or out of inodes."
- "I filled the disk with fallocate, the check failed with exit code one, and passed again after I deleted the file."

## 8. Sources

- df(1), `-P`, `-i`, `-B` — https://man7.org/linux/man-pages/man1/df.1.html
- fallocate(1), preallocate space to a file — https://man7.org/linux/man-pages/man1/fallocate.1.html
- tune2fs(8), `-m` reserved blocks percentage ("Normally, the default ... is 5%") — https://man7.org/linux/man-pages/man8/tune2fs.8.html
- inode(7), what an inode holds — https://man7.org/linux/man-pages/man7/inode.7.html
- Xiaolin (Chinese), 7.1 file systems: inodes and directory entries — https://xiaolincoding.com/os/6_file_system/file_system.html

## 9. Self-check

<details>
<summary>1. df shows 97%, our check says 96%. Who's right?</summary>

Both: the exact share is 96.00%; df rounds up when it prints.
</details>

<details>
<summary>2. One 60 GB file filled the disk. Why did inode usage stay at 1%?</summary>

One file uses one inode, whatever its size.
</details>

<details>
<summary>3. (Only if you really get it) df says the disk is 95% full, but du on / adds up to 10%. What's going on, and how do you free the space without rebooting?</summary>

Usually a large file that was deleted while a process still has it open (a log being written, for example): the name is gone, so `du` can't count it, but the blocks stay allocated until the last process closes it. Find it with `lsof +L1`; restart that process, or truncate the file through `/proc/<pid>/fd/<n>`.
</details>

## 10. Replay time

15 minutes.
