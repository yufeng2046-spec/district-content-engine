#!/usr/bin/env python3
"""Chain chengdu/xa/beijing buckets on CubeMini: launch → monitor → merge → next.

Runs locally; drives CubeMini via launch_cube_details.py (which launches the
crawl with --show, monitors it, and restarts on stall). After each bucket
completes, merges its results into the local DB, then moves to the next.

Robust to monitor crashes (SSH blips): retries the same bucket until it
completes or MAX_ATTEMPTS is hit.

Usage:
    python3 chain_cube_regions.py <region1> <region2> ... [--show]
"""
from __future__ import annotations

import subprocess
import sys
import time

MAX_ATTEMPTS = 6


def main():
    argv = sys.argv[1:]
    show = "--show" in argv
    regions = [a for a in argv if not a.startswith("--")]
    if not regions:
        print("Usage: chain_cube_regions.py <region1> ... [--show]")
        sys.exit(1)
    print(f"[chain] regions={regions} mode={'--show' if show else '--xvfb'}", flush=True)

    for region in regions:
        print(f"\n[chain] === {region} ===", flush=True)
        done = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"[chain] attempt {attempt}/{MAX_ATTEMPTS}: launching/monitoring {region}", flush=True)
            cmd = [sys.executable, "launch_cube_details.py", "--region", region]
            if show:
                cmd.append("--show")
            rc = subprocess.call(cmd)
            if rc == 0:
                print(f"[chain] ✅ {region} done (rc=0)", flush=True)
                done = True
                break
            print(f"[chain] ⚠️ monitor exited rc={rc} (likely SSH blip) — retrying in 30s", flush=True)
            time.sleep(30)
        if not done:
            print(f"[chain] ❌ {region} failed after {MAX_ATTEMPTS} attempts — moving on", flush=True)
            continue
        print(f"[chain] merging {region} into local...", flush=True)
        subprocess.call([sys.executable, "merge_from_cubemini.py", region, "--no-validate"])

    print("[chain] all regions complete", flush=True)


if __name__ == "__main__":
    main()
