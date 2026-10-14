# Hardware benchmark — 2026-09-15/16

Measured on macOS 26.6.2 (Apple Silicon). Raw output in
[`tools/benchmarks/`](../tools/benchmarks/), produced by
[`tools/benchmark_mac.py`](../tools/benchmark_mac.py).

The purpose was to replace three assumptions with measurements: how long generation actually
takes, how much memory the models actually need, and what it costs to swap between them.

## Results

Stable Diffusion XL base 1.0, fp16, on the MPS backend, 1024×1024, 25 steps.

| Stage | Measured | Runs |
|---|---|---|
| SDXL generation | **24.6 s** (σ 0.6) ≈ 0.99 s/step | 5 |
| SDXL pipeline load, warm | 10.1 s | 3 |
| SDXL transfer to MPS | 1.6 s | 3 |
| First-generation warmup | 3.5 s | 3 |
| SDXL unload | 0.27 s | 3 |
| Qwen2.5-14B-4bit load, warm | **0.93 s** | 1 |
| Qwen2.5-14B-4bit generation | 4.75 s / 128 tokens ≈ 27 tok/s | 2 |
| Qwen unload | 0.04 s | 2 |

First-run figures (309 s for SDXL, 250 s for Qwen) are download time, not load time, and are
irrelevant to steady-state behaviour.

## The important finding: swapping is cheap

A full cycle — SDXL loaded, unloaded, language model loaded and used, unloaded, SDXL reloaded —
costs about **18 seconds** of overhead.

This was expected to be far worse, and a design concern was raised that swap cost might make
best-of-N generation unaffordable. It does not.

The reason is an asymmetry worth designing around:

- **MLX loads in under a second** because quantised weights are memory-mapped
- **`diffusers` takes 10-12 seconds** because it deserialises into torch tensors

So the sensible policy is the opposite of a naive least-recently-used cache: **keep SDXL
resident and swap the language model freely.**

## Memory

- SDXL: **6.94 GB**, held in the MPS allocator
- Qwen2.5-14B-4bit: **8.36 GB**, held as ordinary process memory

These use different accounting, which is why MPS allocation reads as zero during language-model
stages. Co-residency would need roughly 15.3 GB.

Available memory during the runs ranged between 6.4 and 16.9 GB — never close to the 48 GB an
earlier plan assumed, and the machine's specification is still unconfirmed. **Because swapping
costs only 18 seconds, co-residency is not required and the question does not block anything.**
Any planning that assumes ~27 GB of simultaneously resident models should be discarded rather
than adjusted.

## Per-request budget

| Stage | Time | Basis |
|---|---|---|
| Dialogue model emits a prompt (~400 tokens) | ~16 s | measured |
| Swap to SDXL | ~17 s | measured |
| Four images generated | ~99 s | measured |
| Swap to the judge | ~1 s | MLX comparison |
| Four judge calls | **~30-60 s (unmeasured)** | estimate |
| Image-text alignment scoring | ~5 s | estimate |
| **Total** | **~3 minutes** | |

An earlier estimate of "2-4 minutes" holds up, *including* the swap costs it had omitted.

## Still unmeasured

**Qwen2-VL judge latency.** It runs several times per request, and because the judge compares two
images per call rather than scoring one, it costs more than a single-image estimate suggests.
This should be measured before the number of candidates per request is fixed.

```bash
python3 tools/benchmark_mac.py --llm mlx-community/Qwen2-VL-7B-Instruct-4bit
```

---

# Deploy VM idle baseline — 2026-10-13

Measured on the cloud VM, not the Mac. Oracle Linux 9.7, aarch64, 1 vCPU, 5642 MB RAM, 4095 MB
swap, 30 GB disk.

The purpose was to establish what the machine costs to merely exist, so that a later measurement
of the JVM alongside Postgres and Redis has something honest to subtract from. "Idle baseline"
here means: no project process running at all — only the operating system and the agents Oracle's
image installs.

## Why the first reading was discarded

The machine was running six VS Code remote-server installations left behind by disconnected
editor sessions — twelve processes, 3.8 GB on disk, one of them 30 days old. `who` reported no
logged-in users, so nothing was in use; the clients had gone and the servers had not.

| | Used | Available | Swap used | Disk used |
|---|---|---|---|---|
| With the editor servers resident | 1453 MB | 4189 MB | 127 MB | 15 GB (49%) |
| After removing them | ~711 MB | ~4930 MB | 121 MB | 11 GB (36%) |

Measuring the fit of a 1 GB JVM heap against the first row would have understated available
memory by roughly 740 MB — about three quarters of the heap being tested.

## Baseline

Twelve samples of `free -m`, ten seconds apart, over two minutes:

| | Range across 12 samples | 
|---|---|
| Memory used | 709–715 MB |
| Memory available | 4927–4933 MB |
| Swap used | 121 MB, unchanging |

The spread is 6 MB, so this is a steady state rather than an average over a varying one.

Largest resident processes at idle, all from Oracle's image rather than the project: `pmlogger`
48 MB, `fluentd` 41 MB, `pmdaproc` 30 MB, `oci-wlp` 27 MB — roughly 200 MB of monitoring
agents in total.

## The finding worth carrying forward

**The machine is already swapping before any project process exists.** 121 MB sits in swap at
idle, held by `firewalld` (23 MB), a `python3` process (20 MB), `fluentd` and its `ruby` (37 MB
between them) and `tuned` (9 MB). Removing the editor servers freed 742 MB of RAM but moved swap
by only 6 MB, which confirms the 121 MB belongs to these long-lived system processes and not to
anything that was cleaned up.

This matters for how the fit question gets answered. With 4 GB of swap configured, the failure
mode under memory pressure is not a clean out-of-memory kill — it is the JVM's pages being
written to disk and the request latency degrading quietly. **A later measurement that reports
only resident set size will therefore record "it fits" for a configuration that thrashes.** Swap
activity has to be reported alongside it.

## What this measurement could not detect

It is an idle reading. No JVM, Postgres or Redis was running, so it says nothing about whether
the three fit together, which is the actual open risk. It also says nothing about CPU: the
machine has one core, and contention between the JVM, the database and the queue is a separate
question that a memory measurement cannot answer.

Available memory for the project, as a working figure to be tested rather than a result:
**~4.9 GB.**
