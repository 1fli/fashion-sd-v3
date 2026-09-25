# Working in this repo

Read this first. It carries context that exists nowhere else — agent memory and session history do
not travel between machines, so this file and the repository are the only things that do.

For what the system *is*, read the [README](README.md). For why choices were made, read
[docs/decisions.md](docs/decisions.md).

## Working principles

**Correctness over speed.** There is no delivery deadline. Do not propose cuts justified only by
schedule — justify them by correctness or by whether they improve the result. Where two approaches
are otherwise close, prefer the more thorough one.

**Every claim must be checkable against what the code actually does.** No asserted result without
the measurement behind it, and no measurement without its sample size.

**Depth over coverage.** A smaller system understood completely beats a larger one assembled from
parts nobody can explain.

## Hard constraints

- **Neutral naming throughout.** No company or organisation names anywhere — packages, repository
  names, documentation, commit messages, code, or file paths. Earlier drafts used a prefixed
  package name; that naming is void.
- The GitHub handle is `1fli`, so `io.github.1fli...` is **not a legal Java package** (a segment
  cannot begin with a digit). Pick something neutral when scaffolding.
- Commit using the git identity configured locally for this repository.
- **No AI attribution in commits or pull requests.** No `Co-Authored-By` trailers naming an
  assistant, no "generated with" footers. The commit history is the author's.
- **Never commit or push without an explicit review.** Stage the changes, show what changed and
  the proposed message, and wait for approval. This holds even when the work was requested and
  the change is obviously correct — the review is the point, not a formality.

## Machine split

| | Role |
|---|---|
| **MacBook** | All development and all GPU work — SDXL, MLX models, kohya training, the Python worker. Claude Code runs here. |
| **Cloud VM** | Deploy target only: Spring Boot, Postgres, Redis. 1 vCPU / 5 GB ARM — too small to also host an interactive session. Reach it over Tailscale and ssh. |

## Documentation discipline

The repository deliberately holds **four documents**. It was briefly fifteen files across four
folders, which was structure built for projected volume rather than actual volume — the same
premature-abstraction mistake the project rejects elsewhere.

**Anything describing how code works belongs in the code.** Prose describing code diverges from it
the first time someone edits without reading. Docs exist only for the four things code cannot
carry: why something was *rejected*, measurements about hardware, methodology for knowing whether
a result is real, and external constraints.

Before adding a document, ask whether it is one of those. If not, it belongs in a comment, a
docstring, or the README.

**Never edit an entry in `docs/decisions.md` to bring it up to date, and never delete one.** Add a
new entry and mark the old superseded, with pointers both ways. An agent's instinct on finding a
stale document is to helpfully update it — that instinct destroys the record this convention
exists to preserve. Update the README in the same commit, since that is what tracks current state.

## Settled — do not re-litigate

Decided after an audit of the previous project, a hardware benchmark, and licence research. Each
has reasoning in [docs/decisions.md](docs/decisions.md). Reopen one only if information appears
that did not exist in September 2026.

Fresh build, not a port · SDXL, not SD 1.5 · train locally, publish everything but the weights ·
Spring Boot server with a Python worker · Redis Streams, not Celery · pairwise comparison, never
absolute scores · no retrieval-augmented generation · live demo behind an access code · one
repository.

Also cut and staying cut: the LAION aesthetic scorer, per-request cost telemetry for local models,
four of five planned plugin interfaces, and N-prompts × M-images best-of-N (collapsed to one
prompt × four seeds).

## Non-negotiable from the first commit

**Every generated image records full provenance.** Schema and reasoning in
`server/src/main/resources/db/migration/V1__create_generation.sql`. It cannot be backfilled;
images generated without it are unusable as evidence, which silently destroys the comparison the
project's main claim rests on.

## Writing norms

- **Define terms on first use, with a worked example.** No compressed shorthand, no bare
  statistics, no citing a line number without saying what it says. A document only its author can
  follow has failed.
- **Verify before asserting.** Do not state properties of a dataset, model or file without
  inspecting it. Label assumptions as assumptions.
- **Never overclaim.** Report sample sizes and confidence intervals, not bare percentages. State
  what a measurement could not have detected.

## Code notes by area

**`server/`** — Spring Boot 3, JVM 21, Gradle (Kotlin DSL). HTTP endpoints, job publication to
Redis, result correlation, persistence via Spring Data JPA and Flyway, Actuator for health and
metrics. No model loading — that is `worker/`. Job state lives in Postgres, not heap: holding
futures in memory loses every in-flight request on restart and makes the at-least-once claim
false. Target VM is 1 vCPU / 5 GB shared with Postgres and Redis, so ~1 GB heap is the ceiling;
verifying the whole set fits is an explicit goal of the first slice.

**`worker/`** — Python 3.11 on the Mac. Consumer loop, SDXL via `diffusers` on MPS, Qwen via MLX,
Qwen2-VL judging **two images per call**. Measured: one image 24.6 s, SDXL load ~10 s, MLX load
0.93 s, full swap cycle ~18 s. **MLX memory-maps its weights so loading is nearly free, while
`diffusers` deserialises and is 10-12× slower — keep SDXL resident and swap language models
freely**, the opposite of a naive cache policy. Structured output uses grammar-constrained
decoding, not validate-and-retry. Idempotency uses a lease (`SET <uuid> NX EX <ttl>`), not a
growing set.

Neither directory is scaffolded yet. Scaffold on the Mac, where Java, Docker and Gradle exist and
the result can actually be compiled and run.

## Current state

Planning complete, no application code. Next is the walking skeleton — one request producing one
image through the real architecture, with no dialogue model, no best-of-N, no judge, no auth.

It exists to surface two risks early: whether Tailscale works as assumed between the VM and a
laptop behind home NAT, and whether 1 vCPU and 5 GB genuinely holds the JVM alongside Postgres and
Redis.

Sequencing beyond that lives in GitHub issues and milestones, not in a document.
