-- Provenance for every generated image.
--
-- The project's central claim is a comparison: images produced with the fine-tuned adapter
-- against images produced without it, everything else held constant. That only holds if
-- "everything else" is actually known.
--
-- None of this is reconstructable after the fact. An image with no recorded seed cannot be
-- regenerated; one with no prompt version cannot be compared against an image made after the
-- prompt changed; one with no model hash cannot be attributed to a training checkpoint. Images
-- generated before these columns exist are permanently unusable as evidence.
--
-- Most of these are not read by the first implementation slice. They are here anyway, because
-- adding them costs minutes now and costs every image generated in the meantime later.

CREATE TABLE generation (
    id                    UUID PRIMARY KEY,

    -- Regenerating the image, and pairing with-adapter against without-adapter runs on an
    -- identical seed. Pairing is what makes a 40-request evaluation set sufficient instead of
    -- needing several hundred: the adapter becomes the only difference between two images.
    seed                  BIGINT       NOT NULL,

    -- Exactly as sent to the pipeline, after any templating. Not the user's original text.
    prompt_positive       TEXT         NOT NULL,
    prompt_negative       TEXT         NOT NULL,

    -- Both the identity and the hash. A filename like 'fashion-lora-epoch7.safetensors' says
    -- nothing about whether the file changed between two runs; a digest does.
    base_model_id         TEXT         NOT NULL,
    base_model_sha256     CHAR(64)     NOT NULL,
    lora_id               TEXT,                    -- null when generating without the adapter
    lora_sha256           CHAR(64),
    lora_weight           REAL,

    sampler               TEXT         NOT NULL,
    scheduler             TEXT         NOT NULL,
    steps                 INTEGER      NOT NULL,
    cfg_scale             REAL         NOT NULL,
    width                 INTEGER      NOT NULL,
    height                INTEGER      NOT NULL,

    -- Which version of the generating code produced this.
    worker_git_sha        CHAR(40)     NOT NULL,

    -- Hash of the dialogue model's system prompt. Changing those instructions changes what the
    -- pipeline produces, so results either side of a change are not comparable.
    system_prompt_version CHAR(64),

    -- Which measuring device evaluated this. Rewording the rubric changes the instrument, so
    -- verdicts under different rubric versions cannot be pooled. Null until judged.
    judge_model_id        TEXT,
    rubric_version        TEXT,

    image_uri             TEXT         NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX generation_created_at_idx ON generation (created_at DESC);
CREATE INDEX generation_lora_idx       ON generation (lora_sha256) WHERE lora_sha256 IS NOT NULL;

-- Known limitation, documented rather than overclaimed: PyTorch on Apple's MPS backend is not
-- guaranteed to produce byte-identical output across versions. A recorded seed reproduces an
-- image closely, not provably exactly. Pin the PyTorch version and state this.
