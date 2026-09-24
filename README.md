# fashion-sd-v3

A conversational AI fashion-design system. You describe a garment; a language model interviews you
across several turns to draw out the specifics; Stable Diffusion XL generates candidates; a
vision-language model compares them and returns the best.

**Status: planning complete, implementation starting.** Architecture and evaluation methodology are
settled. No application code exists yet.

## Why this exists

Two earlier prototypes turned a text prompt into an image through a web UI. This rebuild targets
what was missing: multi-turn intent elicitation, a *measurable* definition of good output, and a
task layer that survives the worker going offline.

The interesting problem here is not image generation. It is **how you know whether a change made
things better** — generative aesthetics have no ground truth, so the measurement design gets as
much attention as the pipeline.

## Architecture

```
Browser ──► Spring Boot (cloud VM) ──► Redis Streams ──► Python worker (MacBook)
                   │                        ▲                      │
               Postgres                     └──── results ─────────┤
                                                                   ├─ SDXL + LoRA
                                                                   ├─ Qwen 2.5 14B (dialogue)
                                                                   └─ Qwen2-VL 7B (judge)
```

Work crosses the language boundary as typed jobs on Redis Streams, with at-least-once delivery,
retries, reclamation of entries abandoned by a dead consumer, and dead-lettering.

**A request flows:**

1. Browser posts a message; the server persists the turn and publishes a `chat` job
2. Worker runs the dialogue model, returning either a follow-up question or a finished prompt
3. On a finished prompt the server publishes a `generate` job — one prompt, four seeds
4. Worker generates four images serially on the GPU, writing provenance for each
5. Server publishes `judge` jobs — **one per image pair**, not per image
6. Worker compares pairs, each twice with the order swapped
7. Server records verdicts and returns the winner

Job state lives in Postgres, not server memory. Holding futures in heap would lose every in-flight
request on restart and make the at-least-once claim false.

**Where things run:**

| | Role | Constraint |
|---|---|---|
| Cloud VM | Spring Boot, Postgres, Redis. Always available. | 1 vCPU / 5 GB ARM. ~1 GB heap. Fit unverified. |
| MacBook | All GPU work and all development. | Over Tailscale, behind home NAT. Offline when the lid closes. |

Inference is Python-bound; the server is JVM **by choice, not necessity**. The cross-language
contract is a deliberate part of the design rather than an accident of tooling.

## Stack

| Layer | Choice |
|---|---|
| Server | Spring Boot 3, JVM 21, Gradle (Kotlin DSL) |
| Persistence | Postgres, Spring Data JPA, Flyway |
| Queue | Redis Streams with consumer groups |
| Worker | Python 3.11 |
| Image generation | SDXL base 1.0 via `diffusers` on MPS, with a locally trained LoRA |
| Dialogue | Qwen 2.5 14B (4-bit) via MLX, grammar-constrained output |
| Judge | Qwen2-VL 7B via `mlx-vlm`, pairwise |
| Alignment check | CLIP — a guard, never a selector |
| Network | Tailscale |

## Deliberately excluded

Worth as much as the list above: each was considered and rejected for a stated reason, and none
should return without new information. Reasoning in [docs/decisions.md](docs/decisions.md).

| Not used | Why |
|---|---|
| Retrieval-augmented generation, pgvector | Self-reinforcing against the same judge that scores the output; unfalsifiable at this data volume |
| Absolute 0-1 quality scores | Vision models cluster in 0.7-0.85 — the signal is smaller than the noise |
| LAION aesthetic predictor | Measures generic prettiness, not whether clothing is good |
| Celery | Python-only; cannot span the language boundary |
| Spring Security / JWT | Single-user demo behind an access code |
| Feature flags, online A/B | Underpowered at this traffic volume; replaced by an offline harness over a frozen request set |
| Per-request cost telemetry | An invented dollar-per-GPU-second constant on a laptop you own is theatre |
| ControlNet | Net-new integration. Deferred, not rejected |
| Published model weights | Training-data provenance and model likeness |

## Measured constraints

Full numbers in [docs/benchmarks.md](docs/benchmarks.md).

- One 1024×1024 image at 25 steps: **24.6 s**. Four candidates ≈ 99 s
- Full model swap cycle: **~18 s**. MLX memory-maps weights and loads in under a second;
  `diffusers` deserialises and takes 10-12 s — so **keep SDXL resident and swap language models
  freely**, the opposite of a naive cache policy
- SDXL holds 6.94 GB, the 14B dialogue model 8.36 GB. Co-residency is not required
- End-to-end request: **~3 minutes**
- A dialogue turn costs ~5 s against ~25 s for an image, so conversations can run concurrently and
  **only generation needs serialising**

## Invariants

- **Every generated image records full provenance** — seed, prompt as sent, model hashes, sampler
  settings, code version. Not backfillable; images without it cannot serve as evidence. Schema in
  `server/src/main/resources/db/migration/`
- **The judge never scores a single image.** It compares two, in both orders
- **No claimed result without a sample size and a confidence interval**

## Layout

```
server/   Spring Boot — HTTP, job publication, persistence
worker/   Python — SDXL, MLX models, the consumer loop. Runs on the Mac
tools/    audit and benchmark scripts
docs/     decisions, evaluation method, benchmarks, training runbook
```

## Documentation

Four documents, deliberately. Anything describing *how* code works belongs in the code.

- [decisions.md](docs/decisions.md) — why each significant choice was made, including what was
  rejected. Code cannot show the absence of Celery
- [evaluation.md](docs/evaluation.md) — how output quality is measured and how the judge is itself
  validated
- [benchmarks.md](docs/benchmarks.md) — measured hardware behaviour
- [train-lora.md](docs/train-lora.md) — the training procedure

## Status of claims

Nothing here asserts a measured quality result. Performance and quality numbers appear only once
measured, with sample sizes and confidence intervals attached.
