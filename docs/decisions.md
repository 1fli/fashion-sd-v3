# Decisions

Why each significant choice was made, and what was rejected. This exists because code can show
what is there but never what was considered and discarded — the absence of Celery is invisible in
a codebase.

**These are historical records, not current truth.** For what the system currently *is*, read the
[README](../README.md). Entries here are not edited to stay current: when a decision changes, add
a new entry at the bottom and mark the old one superseded, with a pointer in both directions. A
decision log containing only correct decisions is one nobody can trust — the value of keeping a
wrong one is the reasoning attached to it.

Two entries are marked **pre-implementation**: reasoned but not yet validated against working
code, and therefore likelier than the others to be superseded.

---

## 1. Build fresh rather than porting the previous project

*Accepted 2026-09-16*

The project was framed as the third generation of an existing one, with a goal of preserving
earlier model work. An audit of `1fli/fashion-sd` found far less to preserve than assumed:

- All project commits fell between 2025-04-24 and 2025-05-03 — 21 commits over ten days. The
  2022-23 generation described in the plan was not in the repository at all
- The stack was Flask, **Streamlit**, and SQLAlchemy defaulting to **SQLite** — not the "Flask +
  React + PostgreSQL" claimed
- Image generation was HTTP calls to an AUTOMATIC1111 web UI, not a `diffusers` pipeline. Moving
  to `diffusers` is a rewrite, not a port
- "LoRA" existed only as the prompt string `<lora:fashion-lora:1.3>`. No training code in any
  repository; a fork of a kohya trainer had zero commits
- **No ControlNet anywhere**, despite it being claimed as existing work
- The repository was a **fork of AUTOMATIC1111/stable-diffusion-webui** with no license set —
  roughly 600 lines of project code under 7,700 upstream commits

Keeping the old code also forced a contradiction: the surviving adapter is SD 1.5 while the plan
targeted SDXL, and the two are incompatible (see 2).

**Decision:** new repository. Carry forward experience, the curated dataset, and the caption
vocabulary — not code.

The old project code never imported web UI source, only spoke HTTP to it, so no copyleft attached
and extraction would have been legal. The question is simply moot now. Claims that rested on the
earlier generations are dropped rather than defended.

## 2. Target SDXL, retiring the SD 1.5 adapter

*Accepted 2026-09-16*

The existing adapter was trained against `chilloutmix_NiPrunedFp32Fix`, a Stable Diffusion 1.5
merge. A LoRA is a set of low-rank deltas shaped to a specific UNet, so an SD 1.5 adapter
**cannot load into SDXL** — different block structure, different attention dimensions, and SDXL
has two text encoders where SD 1.5 has one. The original plan committed to both SDXL and
preserving the adapter. Only one was possible.

Licensing decided it rather than aesthetics:

| | ChilloutMix | SDXL base 1.0 |
|---|---|---|
| License | *Modified* CreativeML OpenRAIL-M | CreativeML Open RAIL++-M |
| Hosting anywhere earning revenue **or donations** | Forbidden | Permitted; SaaS explicit |
| Distributing derivative weights | Must carry the same restrictions | Permitted with license propagation |

OpenRAIL-M defines a derivative broadly enough — "any model created or initialised by transfer of
patterns of weights... to cause the other model to perform similarly" — that an adapter trained
against ChilloutMix plausibly inherits its restrictions, capping the project permanently at a
non-monetised demo.

**Decision:** SDXL base 1.0, retraining the adapter from the existing dataset. This *removes* a
licensing constraint rather than working around it, and avoids shipping a 2022-era base model.

The retrain is not a port of the old recipe — at ~100 images SDXL's much larger UNet overfits far
more readily, so the hyperparameters invert toward lower capacity. See
[train-lora.md](train-lora.md).

## 3. Keep the curated dataset; publish everything except the weights

*Accepted 2026-09-16*

Training data is ~100 images hand-picked from the Kaggle "Fashion Product Images Dataset" —
on-model studio photography on white, closely matching the generation target.

**Provenance.** The images were scraped from Myntra.com, so the uploader could not grant rights he
never held. Training for research is ordinary and low-risk; *publishing the weights* is the part
that does not hold up.

**Likeness.** These are photographs of identifiable working models. An adapter trained on ~100
images of a small number of people can reproduce recognisable faces. For a public project this is
the sharper risk, and it is independent of any license.

**Distribution — investigated and dismissed.** An earlier draft claimed the dataset was
e-commerce flat-lays mismatched to the target. That was asserted without inspecting the images and
was wrong. Switching to a permissively licensed alternative (The Met's CC0 costume collection was
considered) would have changed the product's target aesthetic, not just its data source.

**Decision:** keep the curated subset, train locally, publish training code, configuration,
results and sample outputs — **not the weights**. The fine-tuning claim stays fully demonstrable;
only the binary artifact is withheld.

During evaluation, check that outputs do not reproduce recognisable faces. If they do, that is an
overfitting signal worth acting on regardless.

## 4. A cross-language boundary, crossed with Redis Streams

*Accepted (pre-implementation) 2026-09-16*

Inference is Python-bound — `diffusers`, MLX and `mlx-vlm` have no practical JVM equivalents. That
half is not a choice. The API tier could have been Python too, and FastAPI would have been faster
to build.

But the boundary is where the most distinctive engineering lives: a typed job contract crossing
languages with at-least-once delivery, retry, reclamation of abandoned work, and dead-lettering.
Collapsing it reduces the project to "a web app that calls some models."

The honest framing matters. The boundary is **not forced** — it is chosen, to exercise JVM
production patterns and make the cross-language contract real. If asked "why not FastAPI?", that
is the answer, not a claim that Python could not have served.

Celery would have given a richer task framework but is Python-only and cannot span the boundary.
Redis Streams with consumer groups gives the same fundamentals in a language-neutral way; the cost
is hand-written glue, which is the point.

**Decision:** Spring Boot 3 on JVM 21, Python 3.11 worker, Redis Streams between them, all in one
repository. A single repo keeps the job contract defined once — split across two it drifts, and no
single commit shows a contract change coherently. There is one developer, so the coordination cost
that justifies separate repos does not exist.

Defects already identified in the original design, to be avoided:

- **`XREADGROUP results.*` does not exist.** Redis stream reads take explicit keys; there is no
  wildcard form. Use one `results` stream with `request_id` as a field
- **One stream per request leaks.** Unbounded keys that are never reclaimed. Use `MAXLEN` and a
  job deadline, so a three-day-old job does not run when the laptop wakes
- **In-memory correlation is at-most-once.** Holding a `CompletableFuture` in heap loses every
  in-flight request on restart while the worker publishes results nobody reads — directly
  contradicting the at-least-once claim. Persist job state in Postgres
- **Delivery counts come from `XPENDING`**, not `XINFO STREAM`
- **Idempotency needs a lease** (`SET <uuid> NX EX <ttl>`), not an ever-growing set

A single worker barely exercises reclamation, so it must be tested deliberately: kill the worker
mid-job, show the entry is reclaimed and not executed twice. That test is a deliverable.

## 5. Compare images rather than scoring them

*Accepted (pre-implementation) 2026-09-21*

The obvious design asks a vision model to rate one image on several 0-1 scales. Three problems:
models cluster in 0.7-0.85 so the gap between candidates is smaller than run-to-run variation;
nothing defines what 0.6 versus 0.7 means, so the scale is unstable across sessions; and with
reasoning emitted last, the number is a guess the following text rationalises.

Nothing downstream actually needs a score. Best-of-N selection, checkpoint selection, the adapter
A/B and judge validation all need a *ranking*.

**Decision:** show the judge two images and ask which is better, running every comparison twice
with the order swapped — agreement both ways is a verdict, disagreement is a tie. Reasoning is
emitted before the verdict. Rubric criteria are still assessed, but only to explain why something
lost; they never select.

This also makes position bias measurable rather than invisible, and validating the judge against
hand labels becomes meaningful because humans are also more reliable at pairwise judgements.

The plan's weighted formula `0.6 × judge + 0.3 × CLIP + 0.1 × aesthetic` is deleted — it
contradicted the plan's own architecture section. CLIP is kept only as a **guard**: if the judge's
winners consistently score worse on image-text alignment than its rejects, it is preferring
attractive images that ignore the request.

Method in [evaluation.md](evaluation.md).

## 6. No retrieval-augmented generation

*Accepted 2026-09-16*

The plan included retrieval: summarise the conversation, embed it, retrieve the nearest past
generations scoring above a threshold, feed them as examples, write successes back.

**It is self-reinforcing.** Retrieval is filtered by the judge's own score and the output is then
scored by that same judge. The system narrows toward whatever the judge already likes — mode
collapse with a feedback loop, and the plan had no guard against it.

**It is unfalsifiable at this scale.** At dozens of generations per day, the nearest neighbours to
a request are frequently unrelated, and no measurement could show whether retrieval helped.

The layer also carried concrete defects: the embedding dimension was 384 in the schema and 768 in
the implementation section (`bge-base-en-v1.5` is 768), and an `ivfflat` index was specified for a
table holding a few hundred rows, where it performs worse than no index.

**Decision:** cut retrieval and pgvector entirely.

This is cut on **correctness grounds, not for time** — it stays cut even though calendar time is
not a constraint, because more time does not make a self-reinforcing loop a better idea. If
revisited, it needs a different filter signal — human preference rather than the judge's own
verdict — or the loop returns.

## 7. Live demo behind an access code

*Accepted 2026-09-16*

A live interactive demo was chosen over a recorded walkthrough. That moves the system from
single-user to public-facing and pulls in unbudgeted work: content safety becomes mandatory
(public input, a model capable of explicit output, public display); concurrency and queue caps
matter because one laptop takes ~3 minutes per request strictly serially; a closed laptop must
degrade visibly; prompt injection stops being theoretical; and nothing otherwise stops one visitor
queueing a hundred generations.

**Decision:** publish behind a short access code, shared directly with people invited to try it.

One measure covers concurrency, abuse, safety exposure and compute cost together, and it is
honest — the system is not presented as a public product, because it is not one. Authentication
reduces to a small filter rather than Spring Security with JWT.

A gate reduces exposure; it does not remove the content-safety obligation.
