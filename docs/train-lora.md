# Training the SDXL LoRA

Runs entirely on the MacBook via kohya. **It does not touch the application** — it can start at
any time and run unattended. Only *checkpoint selection* has a dependency: it needs the validated
judge from [evaluation.md](evaluation.md).

Context for why SDXL and why these weights are not published:
[decisions.md, entries 2 and 3](decisions.md).

## The situation

Roughly 100 hand-curated images: on-model studio photography on white backgrounds, selected from
a larger e-commerce dataset.

That count is unremarkable for an SD 1.5 style adapter but **small for SDXL**, whose UNet is
around three times larger and correspondingly quicker to memorise rather than generalise. The
recipe therefore inverts relative to the SD 1.5 one: every choice trades capacity away.

Memorisation is not just a quality problem here. The training images show identifiable working
models, so an over-fitted adapter can reproduce recognisable faces. Reducing capacity addresses
both at once.

## Before training

**Confirm resolution.** The `-small` variant of the source dataset is 60×80 px and unusable. The
full variant is reportedly around 1080×1440, which suits SDXL through aspect-ratio bucketing.
Verify rather than assume.

**Caption deliberately.** The rule: *caption what should stay controllable; leave uncaptioned what
the adapter should absorb.*

- **Do caption:** garment type, colour, pattern, pose, subject
- **Do not caption:** the studio lighting and white background — those are the look being learned

This is likely a latent flaw in the earlier version. Its runtime prompt carried
`studio light, white background`, which implies those were captioned during training — meaning the
adapter never absorbed the aesthetic and it had to be re-prompted on every generation.

**Caption what is actually framed.** Sample images are head-to-mid-thigh, not true full length.
Captioning a three-quarter shot as "full-length portrait" binds that phrase to the wrong framing.

## Configuration

A starting point, not a finished recipe:

| Setting | Value | Reasoning |
|---|---|---|
| `network_dim` | 16 | Rank is the main lever against memorising instances instead of style |
| `network_alpha` | 8 | |
| Text encoder training | **off** | On small SDXL sets this is a primary source of over-fitting, and it is what binds likeness to specific tokens |
| Learning rate | 1e-4 | UNet only |
| Resolution | 1024 base, bucketing on | Handles the ~1080×1440 sources |
| Total steps | ~1500-2500 | e.g. 100 images × 5 repeats × 10 epochs ÷ batch 2 |
| Checkpoint saving | **every epoch** | Non-negotiable — see below |

If recognisable faces start appearing in output, drop to `dim 8 / alpha 4` before changing
anything else.

## Save every epoch

Do not train once and accept the result. Ten checkpoints get ranked by the validated judge against
the frozen request set, and the winner is the one that ships.

This is also why building the evaluation harness early pays for itself: **selecting a checkpoint
is its first job**, before it is ever used for the headline comparison.

## Afterwards

1. Record the SHA-256 of the chosen checkpoint — it goes in every generation's provenance record
2. Check that outputs do not reproduce recognisable faces from the training set; if they do, that
   is an over-fitting signal worth acting on regardless
3. Run the paired comparison against base SDXL on the frozen request set, identical seeds
4. Publish the configuration and the results. **Not the weights.**
