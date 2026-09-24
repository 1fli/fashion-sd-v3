#!/usr/bin/env python3
"""R1 hardware benchmark. Run on the MacBook.

Settles three premises the v3 plan asserts without evidence:
  1. per-stage latency (the plan's table omits model load/unload entirely)
  2. peak resident memory with models co-resident
  3. the cost of one LRU swap cycle, which the plan's ~15 GB claim depends on

Stages are independent; run what you have installed.
  python3 benchmark_mac.py --sdxl --lora /path/to/fashion-lora.safetensors
  python3 benchmark_mac.py --sd15 --base /path/to/chilloutmix.safetensors
  python3 benchmark_mac.py --llm mlx-community/Qwen2.5-14B-Instruct-4bit
  python3 benchmark_mac.py --swap --lora ... --llm ...
"""

import argparse
import gc
import json
import platform
import time
from contextlib import contextmanager
from datetime import datetime, timezone

RESULTS = []


def rss_gb():
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1e9
    except ImportError:
        import resource

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return maxrss / 1e9 if platform.system() == "Darwin" else maxrss / 1e6


def sys_available_gb():
    try:
        import psutil

        return psutil.virtual_memory().available / 1e9
    except ImportError:
        return float("nan")


def mps_alloc_gb():
    try:
        import torch

        if hasattr(torch, "mps") and hasattr(torch.mps, "current_allocated_memory"):
            return torch.mps.current_allocated_memory() / 1e9
    except Exception:
        pass
    return float("nan")


@contextmanager
def timed(label):
    gc.collect()
    before_rss = rss_gb()
    t0 = time.perf_counter()
    yield
    dt = time.perf_counter() - t0
    after_rss = rss_gb()
    RESULTS.append(
        {
            "stage": label,
            "seconds": round(dt, 2),
            "rss_gb": round(after_rss, 2),
            "rss_delta_gb": round(after_rss - before_rss, 2),
            "mps_alloc_gb": round(mps_alloc_gb(), 2),
            "sys_avail_gb": round(sys_available_gb(), 2),
        }
    )
    print(
        f"  [{label}] {dt:7.2f}s   rss={after_rss:5.2f}GB (+{after_rss - before_rss:.2f})   "
        f"avail={sys_available_gb():.1f}GB"
    )


def free_torch():
    import torch

    gc.collect()
    if hasattr(torch, "mps"):
        try:
            torch.mps.empty_cache()
        except Exception:
            pass


def bench_diffusion(args, xl: bool):
    import torch
    from diffusers import StableDiffusionXLPipeline, StableDiffusionPipeline

    tag = "sdxl" if xl else "sd15"
    cls = StableDiffusionXLPipeline if xl else StableDiffusionPipeline
    model = args.base or (
        "stabilityai/stable-diffusion-xl-base-1.0" if xl else "runwayml/stable-diffusion-v1-5"
    )
    res = args.resolution or (1024 if xl else 512)

    print(f"\n== {tag.upper()} == model={model} res={res}")

    with timed(f"{tag}:pipeline_load"):
        if str(model).endswith(".safetensors"):
            pipe = cls.from_single_file(model, torch_dtype=torch.float16)
        else:
            pipe = cls.from_pretrained(model, torch_dtype=torch.float16, use_safetensors=True)

    with timed(f"{tag}:to_mps"):
        pipe = pipe.to("mps")

    if args.lora:
        with timed(f"{tag}:lora_load"):
            pipe.load_lora_weights(args.lora)

    with timed(f"{tag}:warmup_gen_1step"):
        pipe("a model wearing a red dress, studio light", num_inference_steps=1, height=res, width=res)

    for i in range(args.runs):
        with timed(f"{tag}:gen_{args.steps}step_run{i + 1}"):
            pipe(
                "a fashion model wearing an elegant floral dress, full-length, studio lighting",
                num_inference_steps=args.steps,
                height=res,
                width=res,
            )

    if args.keep:
        return pipe
    with timed(f"{tag}:unload"):
        del pipe
        free_torch()
    return None


def bench_llm(args):
    from mlx_lm import load, generate

    print(f"\n== LLM == {args.llm}")
    with timed("llm:load"):
        model, tokenizer = load(args.llm)

    prompt = (
        "You are a fashion prompt engineer. The user wants a 70s-revival festival outfit. "
        "Ask one clarifying question, then emit JSON."
    )
    with timed("llm:generate_128tok"):
        generate(model, tokenizer, prompt=prompt, max_tokens=128, verbose=False)

    if args.keep:
        return model, tokenizer
    with timed("llm:unload"):
        del model, tokenizer
        gc.collect()
    return None


def bench_swap(args):
    """The LRU cycle the plan's ~15 GB peak depends on."""
    print("\n== SWAP CYCLE == (what the plan's LRU design costs per request)")
    args.keep = True
    args.runs = 1

    pipe = bench_diffusion(args, xl=not args.sd15)
    with timed("swap:unload_diffusion"):
        del pipe
        free_torch()

    llm = bench_llm(args)
    with timed("swap:unload_llm"):
        del llm
        gc.collect()

    args.keep = False
    bench_diffusion(args, xl=not args.sd15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdxl", action="store_true")
    ap.add_argument("--sd15", action="store_true")
    ap.add_argument("--llm", metavar="MLX_REPO")
    ap.add_argument("--swap", action="store_true", help="measure a full LRU swap cycle")
    ap.add_argument("--base", help="local .safetensors or HF repo id for the diffusion base")
    ap.add_argument("--lora", help="path to the LoRA .safetensors")
    ap.add_argument("--resolution", type=int)
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--keep", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--out", default="r1_benchmark.json")
    args = ap.parse_args()

    if not any([args.sdxl, args.sd15, args.llm, args.swap]):
        ap.error("pick at least one of --sdxl / --sd15 / --llm / --swap")

    print("=" * 74)
    print(f"R1 benchmark  {platform.platform()}  python {platform.python_version()}")
    print(f"available RAM at start: {sys_available_gb():.1f} GB")
    print("=" * 74)

    try:
        if args.swap:
            bench_swap(args)
        else:
            if args.sdxl:
                bench_diffusion(args, xl=True)
            if args.sd15:
                bench_diffusion(args, xl=False)
            if args.llm:
                bench_llm(args)
    except ImportError as e:
        print(f"\nMISSING DEPENDENCY: {e}")
        print("  diffusion stages need: pip install torch diffusers transformers accelerate peft")
        print("  llm stage needs:       pip install mlx-lm")
    except Exception as e:
        print(f"\nSTAGE FAILED: {type(e).__name__}: {e}")

    if not RESULTS:
        return

    print("\n" + "=" * 74)
    print(f"{'stage':<34}{'sec':>8}{'rss GB':>9}{'Δrss':>8}{'avail':>8}")
    print("-" * 74)
    for r in RESULTS:
        print(
            f"{r['stage']:<34}{r['seconds']:>8.2f}{r['rss_gb']:>9.2f}"
            f"{r['rss_delta_gb']:>8.2f}{r['sys_avail_gb']:>8.1f}"
        )
    print("=" * 74)

    gen = [r for r in RESULTS if ":gen_" in r["stage"]]
    loads = [r for r in RESULTS if r["stage"].endswith(("pipeline_load", "llm:load", ":to_mps"))]
    if gen:
        avg = sum(r["seconds"] for r in gen) / len(gen)
        print(f"\nmean generation: {avg:.1f}s  ->  4 images = {avg * 4 / 60:.1f} min")
    if loads:
        print(f"total model load time this run: {sum(r['seconds'] for r in loads):.1f}s")
    print(f"peak RSS observed: {max(r['rss_gb'] for r in RESULTS):.2f} GB")

    payload = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "args": vars(args),
        "results": RESULTS,
    }
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nwrote {args.out} — send this back for the plan revision")


if __name__ == "__main__":
    main()
