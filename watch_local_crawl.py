#!/usr/bin/env python3
"""Watch local crawls and restart on stall; chain across a queue of regions.

The local --show crawl can silently hang on a wedged page/browser (no exception
raised, loop never advances). This watchdog detects "log unchanged for N minutes"
and restarts the current --details-only crawl — the DB cursor resumes from the
next un-done row, so nothing is lost. It then moves on to the next region in the
queue when the current one completes.

Stall threshold defaults to 15 min — long enough to outlast the --show captcha
wait (max 10 min, where a human solves and the log resumes) yet short enough to
catch a true page-hang (hours of silence).

Usage:
    python3 watch_local_crawl.py <region1> <region2> ... [--stall-min M] [--log-dir D]

Logs go to D/details_<region>.log (default /tmp).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

STALL_MIN = 15.0
LOG_DIR = "/tmp"


def log_path(region: str) -> str:
    return os.path.join(LOG_DIR, f"details_{region}.log")


def watch_region(region: str) -> None:
    """Watch one region's crawl until it completes (Done. / All communities have detail)."""
    log = log_path(region)
    cmd = [sys.executable, "data/scrape_anjuke.py", "--region", region,
           "--details-only", "--show"]
    env = dict(os.environ)
    env["PYTHONPATH"] = "."

    # If no crawl is running for this region, start one.
    proc_check = subprocess.run(["pgrep", "-f", f"scrape_anjuke.py --region {region}"],
                                capture_output=True)
    if proc_check.returncode != 0:
        print(f"[watchdog] launching {region}", flush=True)
        subprocess.Popen(cmd, env=env, stdout=open(log, "a"), stderr=subprocess.STDOUT)

    last_size = os.path.getsize(log) if os.path.exists(log) else 0
    last_change = time.time()

    while True:
        time.sleep(60)
        tail = ""
        if os.path.exists(log):
            with open(log, "rb") as f:
                f.seek(max(0, os.path.getsize(log) - 400))
                tail = f.read().decode(errors="replace")
        if "Done." in tail or "All communities have detail data" in tail:
            print(f"[watchdog] ✅ {region} complete.", flush=True)
            return

        size = os.path.getsize(log) if os.path.exists(log) else 0
        if size != last_size:
            last_size = size
            last_change = time.time()
        elif time.time() - last_change > STALL_MIN * 60:
            print(f"[watchdog] ⚠️ STALL — {region} log unchanged {STALL_MIN}min. Restarting...", flush=True)
            subprocess.run(["pkill", "-f", f"scrape_anjuke.py --region {region}"], capture_output=True)
            time.sleep(3)
            with open(log, "a") as f:
                f.write(f"\n[watchdog] restart at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            subprocess.Popen(cmd, env=env, stdout=open(log, "a"), stderr=subprocess.STDOUT)
            last_size = os.path.getsize(log)
            last_change = time.time()


def main():
    global STALL_MIN, LOG_DIR
    argv = sys.argv[1:]
    regions = []
    i = 0
    while i < len(argv):
        if argv[i] == "--stall-min" and i + 1 < len(argv):
            STALL_MIN = float(argv[i + 1]); i += 2
        elif argv[i] == "--log-dir" and i + 1 < len(argv):
            LOG_DIR = argv[i + 1]; i += 2
        else:
            regions.append(argv[i]); i += 1
    if not regions:
        print("Usage: watch_local_crawl.py <region1> <region2> ... [--stall-min M]")
        sys.exit(1)
    print(f"[watchdog] queue: {regions} | stall={STALL_MIN}min | logs={LOG_DIR}/details_<region>.log", flush=True)
    for region in regions:
        watch_region(region)
    print("[watchdog] all regions complete.", flush=True)


if __name__ == "__main__":
    main()
