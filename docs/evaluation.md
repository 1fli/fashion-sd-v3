# Evaluation methodology

How we decide whether an image is good, and whether a change made things better.

Generative aesthetics have no ground truth, so this is the part of the system that most needs
designing rather than assuming. It determines what pipeline stages exist, so it is settled before
the task layer is built.

The decision to compare rather than score is recorded in
[decisions.md, entry 5](decisions.md); this document is the working spec.

---

## 1. The core decision: compare two images, don't score one

### The approach this replaces

The obvious design asks the vision model to look at one image and output three numbers between 0
and 1 — `intent_match`, `fashion_quality`, `aesthetic` — plus a `reasoning` string, listed last.

### Why that doesn't work

**Vision models are bad at absolute numbers.** Ask one to rate images 0-1 and almost everything
comes back between 0.7 and 0.85. It won't use the bottom of the scale. So the gap between your
best and worst candidate ends up smaller than the model's own random variation — you're reading
noise.

**Nothing defines what the numbers mean.** There is no stated difference between 0.6 and 0.7. So
"0.7" doesn't mean the same thing on Tuesday as it did on Monday, or on a dress as on a jacket.
You can't compare across time, which is the entire point of measuring.

**Reasoning is listed last.** Language models generate text in order. If the number comes first,
the model picks a number and then writes a justification for it. Put the reasoning first and the
number is a conclusion instead of a guess. This costs nothing to fix.

### What we do instead

Notice that nothing we actually want to do needs a score. Everything needs a **ranking**:

| What we're doing | The question we're really asking |
|---|---|
| Picking the best of 4 generated images | Which of these is best? |
| Choosing which LoRA training checkpoint to ship | Which epoch is best? |
| Proving the LoRA helped | Does LoRA beat no-LoRA? |
| Checking the judge is trustworthy | Do the judge and I pick the same winner? |

So we show the judge **two images at a time and ask which is better.** This is what vision models
are most reliable at, and — importantly — it's what *humans* are most reliable at too, which is
what makes checking the judge against yourself meaningful.

The four rubric criteria (below) are still scored, but only to explain *why* something lost.
They never pick the winner.

### Controlling for a real and annoying bias

Vision models often prefer whichever image you showed them first, regardless of content. It's a
well-documented failure and it will silently corrupt everything if ignored.

The fix is cheap: **run every comparison twice, swapping which image goes first.**

- Same winner both times → trust it
- Different winner → record it as a tie, not a coin flip

How often it flips becomes a number we report. A judge that flips constantly isn't measuring
anything, and knowing that is the difference between an instrument and a guess.

---

## 2. What the judge looks for

The target look is **on-model studio photography on a white background**, which is what the
curated training set contains.

The plan's `fashion_quality` and `aesthetic` mean roughly the same thing, and neither can be
checked. Replace them with four criteria chosen because they're what actually goes wrong in
AI-generated fashion images:

| Criterion | What it catches |
|---|---|
| **Intent match** | Is the garment the requested type, colour, era, occasion? |
| **Garment coherence** | Seams, drape, symmetry, closures — could this actually be sewn? |
| **Human plausibility** | Hands, limbs, faces — the classic diffusion failures |
| **Photographic execution** | Lighting, framing, background consistent with studio-on-white |

**The judge writes its observations first, then names a winner.**

The rubric text gets a version number. If you reword it, you've changed the measuring device, and
results from before the change can't be compared to results after. Same principle as not
switching rulers halfway through measuring a room.

---

## 3. Checking the judge against yourself

This is one of the four things worth protecting, because it's the difference between
*"my judge gave it 0.82"* — which means nothing, since the judge is unproven — and
*"my judge picks the same winner I do 78% of the time."*

### The comparison pairs are free

Every best-of-4 run gives you 4 images. Four images make 6 possible pairs. Twenty generations
gives you 120 pairs, and they come from exactly the kind of images the judge will see in real
use. No separate data collection needed.

### The protocol

1. Take about 80 pairs.
2. **You** pick the winner of each: A, B, or tie. Do this before looking at any judge output, so
   you aren't anchored by it.
3. Run the judge on the same pairs, both orderings.
4. Compute the three numbers below.
5. A week later, **re-label 20% of them without looking at your first answers.**

### The three numbers, explained

**Raw agreement** — out of 100 pairs, how many times did you and the judge pick the same winner?
Say 70.

**Cohen's kappa** — raw agreement alone is misleading. Suppose that in your set, image A happens
to win 70% of the time. Then a lazy judge that *always* says "A" would still agree with you about
58% of the time, purely by luck. So 70% agreement isn't 70% skill — some of it is the base rate.

Kappa subtracts out the luck and reports what's left:

- **0.0** = no better than guessing
- **1.0** = perfect agreement
- Rough reading: below 0.4 weak · 0.4-0.6 moderate · 0.6-0.8 good · above 0.8 strong

Kappa is the number that survives scrutiny; raw agreement is the number that sounds good.

**Order-flip rate** — how often did swapping the image order change the judge's answer? This is
the position-bias check from section 1.

### Why you re-label a week later

You are not perfectly consistent either. If you compare your two passes and find you agree with
*yourself* 85% of the time, then 85% is the **ceiling** — no judge can beat the human it's being
measured against.

That reframes everything. A judge at 80% isn't "80% accurate, could be better." It's reaching
**94% of the maximum achievable** (80 ÷ 85). Almost nobody does this check, it costs an hour, and
it turns a mediocre-sounding number into a strong one — honestly.

### Where the thumbs up/down fits

The live demo's thumbs up/down is a weaker signal — it rates one image rather than comparing two.
Its real job is **drift detection**: if agreement drops after you change a model or a prompt,
something regressed. This is what finally makes that button do something; in the original plan it
was collected and never used by anything.

---

## 4. The frozen test set

A fixed list of **requests** (not images) — about 40, spanning garment types, colours, occasions,
eras, and subject variations. Each gets a **fixed random seed**. It's versioned, and if it
changes, old results don't carry over.

### Why fixed seeds matter much more than they look

Two ways to test whether the LoRA helps:

**Unpaired** — generate 40 images without the LoRA, 40 *different* images with it, compare the two
piles. Problem: image generation is random. A lot of the difference between the piles is just
which random images you happened to get. You need hundreds of samples before the LoRA's effect
outgrows that noise.

**Paired** — same request, same seed, generated twice: once with the LoRA, once without. Now the
images are identical in every respect *except* the LoRA. The randomness cancels out.

Pairing is why 40 requests is enough instead of several hundred. It's the single highest-value
methodological choice in this document.

---

## 5. The experiments, and what order they go in

Calibration comes first. Choosing a LoRA checkpoint using an unproven judge would be circular —
exactly the problem this phase exists to eliminate.

| Step | What it is | What it needs first | What it gives you |
|---|---|---|---|
| **1** | Generate a pool of images with plain SDXL | Just the image generation stage | Pairs to label |
| **2** | Check the judge against yourself | Step 1 + your hand labels | Agreement, kappa, flip rate, your ceiling |
| **3** | Pick the best LoRA checkpoint | Step 2 + the 10 saved epochs | Which epoch ships |
| **4** | Prove the LoRA beats plain SDXL | Step 3 + frozen set, paired seeds | Win rate + confidence interval |
| **5** | Compare pipeline variants | Real traffic, much later | Deferred until there is enough traffic to be meaningful |

**Step 2 only needs image generation.** No Spring Boot, no Redis, no LLM, no frontend. So the
whole evaluation system can be built and proven long before the distributed system exists — and
it should be, because step 3 decides which LoRA you actually ship.

---

## 6. What CLIP is for

CLIP is a model that measures how well an image matches a text description.

**The original design contradicted itself about it.** In the architecture section it said CLIP and the
aesthetic scorer should *not* decide which image wins — they're just sanity checks. But later, in
the evaluation phase, it puts them into a weighted formula
(`0.6 × judge + 0.3 × CLIP + 0.1 × aesthetic`) that *does* pick the winner. Both can't be true.

**We keep the first version.** CLIP doesn't choose anything. It's a tripwire:

> Record CLIP alongside every judge verdict. If the judge's chosen winners consistently have
> *worse* CLIP scores than the images it rejected, the judge is picking pretty pictures that
> ignore what was asked for.

CLIP answers "is the judge cheating?", not "which image is best." The weighted formula is
deleted, and the LAION aesthetic scorer is dropped entirely — it measures generic prettiness, not
whether clothing is any good.

---

## 7. What gets recorded for every image

Everything in this document depends on being able to say exactly how a given image was produced.
Without that, the frozen test set becomes meaningless the moment anything changes, and no claim
of improvement can be supported.

The full field list, with the reasoning behind each column, is the schema itself:
**`server/src/main/resources/db/migration/V1__create_generation.sql`**. It must be in place from
the first commit — it cannot be backfilled.

---

## 8. Reporting results honestly

Three habits:

**Always give the sample size.** "n=40" means the result rests on 40 comparisons. A percentage
without it is unreadable.

**Always give a confidence interval, not a bare percentage.** Writing
*"68% (95% CI 54-80%, n=40)"* means: across 40 comparisons the LoRA won 68% of them, and the true
win rate is probably somewhere between 54% and 80%.

Why that range matters: 50% would mean the LoRA does nothing — a coin flip. Since the bottom of
the range (54%) is still above 50%, the result holds. Had the range run 45-85%, the honest
conclusion would be "can't tell yet," even though the headline still said 68%.

**Getting the interval — the bootstrap.** Instead of assuming a formula, take your 40 results and
randomly resample 40 of them *with replacement*, thousands of times, recomputing the win rate
each time. The middle 95% of those recomputed values is your interval. It's just measuring how
much the answer wobbles when the sample shifts.

**Testing it — the sign test.** Counts how many times LoRA beat base and asks whether that split
is far enough from 50/50 to be unlikely by chance.

**Say what you could and couldn't have detected.** With 40 paired comparisons this design can
reliably spot a win rate around 70% or higher; a smaller real improvement would need more
samples. Stating this upfront answers the obvious follow-up question before it's asked, and shows
you understand the limits of your own instrument.

### The sentence all of this buys you

> *"The LoRA wins 68% of paired comparisons (95% CI 54-80%, n=40), judged by a rubric that agrees
> with my own preferences at κ=0.61, against a self-consistency ceiling of 0.74."*

That holds up to questioning. `AVG(vlm_score)` does not.

---

## 9. What this means for the task layer

- The judge is its **own job type**, and its unit of work is a **pair of images**, not one image
- Comparisons don't depend on each other, so they can run in parallel — only image generation is
  stuck being serial on the one GPU
- Every job carries the provenance fields defined in the `generation` table schema
- The evaluation harness runs **offline and on demand** against the frozen set. It isn't in the
  live request path, so it needs no latency guarantees
- No pipeline variants, no feature flags, no RAG retrieval stage

---

## 10. Still open

- **Judge speed is unmeasured.** Qwen2-VL 7B latency is the one gap left in the hardware
  benchmark, and pairwise
  comparison sends it *two* images per call — so it costs more than the single-image estimate.
  Worth measuring before fixing how many candidates best-of-N generates.
- **Run one commercial judge over the same pairs** as a reference point. If the local model scores
  much lower agreement, the ceiling is the model. If both score similarly low, the rubric is the
  problem. Cheap, and it tells you which thing to fix.
