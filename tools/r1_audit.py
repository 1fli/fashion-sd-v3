#!/usr/bin/env python3
"""R1 artifact audit. Run on the MacBook. Stdlib only for `lora`; `dataset` uses PIL if present."""

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def read_safetensors_header(path):
    with open(path, "rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        if n <= 0 or n > (1 << 28):
            raise ValueError(f"implausible header length {n}; not a safetensors file?")
        return json.loads(f.read(n))


def classify_architecture(tensor_names, metadata):
    """Returns (verdict, confidence, evidence[])."""
    evidence = []

    declared = metadata.get("ss_base_model_version") or metadata.get("ss_sd_model_name")
    if declared:
        evidence.append(f"kohya metadata declares base: {declared}")

    has_te1 = any(k.startswith("lora_te1_") for k in tensor_names)
    has_te2 = any(k.startswith("lora_te2_") for k in tensor_names)
    has_te = any(k.startswith("lora_te_") for k in tensor_names)

    if has_te2:
        evidence.append("found `lora_te2_` keys -> dual text encoder")
    if has_te1:
        evidence.append("found `lora_te1_` keys")
    if has_te:
        evidence.append("found `lora_te_` keys -> single text encoder")

    # SDXL has no transformer blocks on down_blocks_0 / up_blocks_2; SD1.5 does.
    sd15_only = [k for k in tensor_names if "down_blocks_0_attentions" in k]
    if sd15_only:
        evidence.append(f"found {len(sd15_only)} `down_blocks_0_attentions` keys (SD1.x UNet shape)")

    mid_2560 = any("mid_block" in k and "1280" in k for k in tensor_names)

    if has_te2:
        verdict, conf = "SDXL", "high"
    elif has_te and sd15_only:
        verdict, conf = "SD 1.x", "high"
    elif declared and "xl" in str(declared).lower():
        verdict, conf = "SDXL", "medium"
    elif declared and ("v1" in str(declared).lower() or "1.5" in str(declared)):
        verdict, conf = "SD 1.x", "medium"
    elif sd15_only:
        verdict, conf = "SD 1.x", "medium"
    else:
        verdict, conf = "UNDETERMINED", "low"

    return verdict, conf, evidence


def cmd_lora(args):
    path = Path(args.path).expanduser()
    if not path.is_file():
        sys.exit(f"not a file: {path}")

    print("=" * 70)
    print(f"LoRA: {path}")
    print("=" * 70)
    print(f"size      : {path.stat().st_size / 1e6:.1f} MB")
    print(f"sha256    : {sha256(path)}")

    try:
        header = read_safetensors_header(path)
    except Exception as e:
        sys.exit(f"\nFAILED to parse as safetensors: {e}")

    metadata = header.pop("__metadata__", {})
    tensor_names = list(header.keys())

    print(f"tensors   : {len(tensor_names)}")
    total_params = sum(
        _prod(v["shape"]) for v in header.values() if isinstance(v, dict) and "shape" in v
    )
    print(f"parameters: {total_params:,}")

    verdict, conf, evidence = classify_architecture(tensor_names, metadata)
    print()
    print("-" * 70)
    print(f"ARCHITECTURE VERDICT: {verdict}  (confidence: {conf})")
    print("-" * 70)
    for line in evidence:
        print(f"  - {line}")
    if verdict == "SD 1.x":
        print("\n  => This LoRA CANNOT be loaded into SDXL. Confirms the plan's Goal 4 /")
        print("     Phase 5 contradiction. Either stay on SD 1.5 or retrain for SDXL.")

    if metadata:
        print()
        print("-" * 70)
        print("KOHYA TRAINING METADATA (recovers the training config)")
        print("-" * 70)
        interesting = [
            "ss_base_model_version", "ss_sd_model_name", "ss_resolution",
            "ss_network_module", "ss_network_dim", "ss_network_alpha",
            "ss_learning_rate", "ss_text_encoder_lr", "ss_unet_lr",
            "ss_num_train_images", "ss_num_reg_images", "ss_num_epochs",
            "ss_max_train_steps", "ss_batch_size_per_device", "ss_optimizer",
            "ss_lr_scheduler", "ss_mixed_precision", "ss_seed", "ss_clip_skip",
            "ss_noise_offset", "ss_training_started_at", "ss_output_name",
        ]
        for k in interesting:
            if k in metadata:
                print(f"  {k:28} = {metadata[k]}")

        for blob_key, label in [("ss_dataset_dirs", "DATASET DIRS"),
                                ("ss_tag_frequency", "TAG FREQUENCY (top 25)")]:
            if blob_key in metadata:
                print(f"\n  {label}:")
                try:
                    parsed = json.loads(metadata[blob_key])
                    if blob_key == "ss_tag_frequency":
                        flat = Counter()
                        for _, tags in parsed.items():
                            flat.update(tags)
                        for tag, n in flat.most_common(25):
                            print(f"    {n:6}  {tag}")
                        print(f"    ({len(flat)} distinct tags total)")
                    else:
                        print("    " + json.dumps(parsed, indent=4).replace("\n", "\n    "))
                except Exception:
                    print(f"    {metadata[blob_key][:500]}")

        unlisted = sorted(set(metadata) - set(interesting) - {"ss_dataset_dirs", "ss_tag_frequency"})
        if unlisted:
            print(f"\n  other metadata keys present: {', '.join(unlisted)}")
    else:
        print("\n  (no __metadata__ block — training config not recoverable from the file)")

    if args.dump_json:
        out = Path(args.dump_json)
        out.write_text(json.dumps({"metadata": metadata, "tensors": tensor_names}, indent=2))
        print(f"\nwrote full header -> {out}")


def _prod(shape):
    n = 1
    for d in shape:
        n *= d
    return n


def cmd_dataset(args):
    root = Path(args.path).expanduser()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")

    print("=" * 70)
    print(f"Dataset: {root}")
    print("=" * 70)

    images = [p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXTS]
    captions = [p for p in root.rglob("*.txt")]
    total_bytes = sum(p.stat().st_size for p in images)

    print(f"images      : {len(images)}")
    print(f"caption .txt: {len(captions)}")
    print(f"total size  : {total_bytes / 1e6:.1f} MB")

    if not images:
        return

    print(f"\nby extension:")
    for ext, n in Counter(p.suffix.lower() for p in images).most_common():
        print(f"  {ext:8} {n}")

    print(f"\ntop-level subdirs (kohya repeat dirs):")
    for d, n in Counter(
        p.relative_to(root).parts[0] for p in images if len(p.relative_to(root).parts) > 1
    ).most_common(20):
        print(f"  {n:6}  {d}")

    try:
        from PIL import Image
    except ImportError:
        print("\n(install Pillow for resolution stats: pip install Pillow)")
        return

    res = Counter()
    sample = images if len(images) <= args.max_probe else images[:: len(images) // args.max_probe]
    for p in sample:
        try:
            with Image.open(p) as im:
                res[im.size] += 1
        except Exception:
            res["UNREADABLE"] += 1
    print(f"\nresolutions (probed {sum(res.values())} of {len(images)}):")
    for size, n in res.most_common(15):
        print(f"  {n:6}  {size}")

    print(f"\nchecksum manifest of first {min(len(images), args.max_hash)} images:")
    digest = hashlib.sha256()
    for p in sorted(images)[: args.max_hash]:
        digest.update(sha256(p).encode())
    print(f"  rolling sha256 = {digest.hexdigest()}")


def main():
    ap = argparse.ArgumentParser(description="R1 artifact audit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_lora = sub.add_parser("lora", help="inspect a LoRA .safetensors")
    p_lora.add_argument("path")
    p_lora.add_argument("--dump-json", help="write full header+metadata to this path")
    p_lora.set_defaults(func=cmd_lora)

    p_ds = sub.add_parser("dataset", help="audit a training dataset directory")
    p_ds.add_argument("path")
    p_ds.add_argument("--max-probe", type=int, default=300)
    p_ds.add_argument("--max-hash", type=int, default=50)
    p_ds.set_defaults(func=cmd_dataset)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
