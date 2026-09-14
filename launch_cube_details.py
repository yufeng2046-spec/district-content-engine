#!/usr/bin/env python3
"""CubeMini details-only auto-launcher with stall-recovery monitoring.

Launches a --details-only crawl on CubeMini (its own IP / Xvfb), optionally
split by --offset/--limit, and keeps it running until the slice is done:

  - polls the remote log every 30s
  - on 3 min of no progress → pkill + relaunch with the SAME offset/limit
    (safe: --details-only reloads `detail_scraped_at IS NULL ORDER BY
    community_id ... OFFSET N LIMIT M`, which resumes at the next un-done
    row of that slice)
  - exits 0 on "Done." / "All communities have detail data"

Usage:
    python3 launch_cube_details.py --region shenzhen --offset 6333 --limit 6332 [--pkill]
    python3 launch_cube_details.py --region datong_pingcheng [--pkill]
"""
from __future__ import annotations

from sync_state_to_cubemini import ssh_exec
import sys, time

DONE_MARKERS = ("Done.", "All communities have detail data")
STALL_ROUNDS = 6        # 6 × 30s = 3 min stall before restart
POLL_SEC = 30
MAX_ROUNDS = 30


def _ssh(cmd: str, timeout: int = 5, tries: int = 10, delay: float = 8):
    """ssh_exec with retry — the jump-host tunnel drops connections transiently."""
    for i in range(tries):
        try:
            return ssh_exec(cmd, timeout=timeout)
        except Exception as e:
            if i < tries - 1:
                print(f"  [ssh retry {i + 1}] {str(e)[:80]}")
                time.sleep(delay)
    raise RuntimeError(f"ssh_exec failed after {tries} tries: {cmd[:80]}")


def parse_args():
    argv = sys.argv[1:]
    region = None
    offset, limit = 0, None
    pkill = False
    show_wait = False
    i = 0
    while i < len(argv):
        if argv[i] == "--region" and i + 1 < len(argv):
            region = argv[i + 1]; i += 2
        elif argv[i] == "--offset" and i + 1 < len(argv):
            offset = int(argv[i + 1]); i += 2
        elif argv[i] == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1]); i += 2
        elif argv[i] == "--pkill":
            pkill = True; i += 1
        elif argv[i] == "--show":
            show_wait = True; i += 1
        else:
            i += 1
    if not region:
        print("Error: --region required")
        sys.exit(1)
    if limit is not None and limit <= 0:
        print("Error: --limit must be > 0")
        sys.exit(1)
    return region, offset, limit, pkill, show_wait


def _is_running() -> bool:
    """True if any scrape_anjuke process is running on CubeMini.

    Fail-safe: transient SSH failures return empty output — treat those as
    "assume running" so we NEVER launch a duplicate (a duplicate on the same IP
    is far worse than a missed restart). Only a confirmed count of 0 allows launch.
    """
    for _ in range(3):
        out, _ = _ssh("ps aux | grep scrape_anjuke | grep -v grep | wc -l", timeout=8)
        s = (out or "").strip()
        if s.isdigit():
            return int(s) > 0
        time.sleep(2)
    print("  [warn] _is_running could not confirm idle — assuming running (no duplicate launch)")
    return True


def launch(region: str, offset: int, limit: int | None, show_wait: bool = False):
    slice_arg = ""
    if limit is not None:
        slice_arg = f"--offset {offset} --limit {limit}"
    mode_arg = "--show" if show_wait else "--xvfb"
    cmd = (f"cd /home/frank/district-content-engine && "
           f"DISPLAY=:99 PYTHONPATH=/home/frank/district-content-engine "
           f"nohup /home/frank/crawler-venv/bin/python3 data/scrape_anjuke.py "
           f"--region {region} --details-only {slice_arg} {mode_arg} "
           f">> /tmp/cube_{region}.log 2>&1 &")
    try:
        ssh_exec(cmd, timeout=8)
    except Exception as e:
        print(f"  (launch ssh timeout ok: {e})")


def main():
    region, offset, limit, pkill, show_wait = parse_args()
    log = f"/tmp/cube_{region}.log"
    # --show waits up to 10 min for a human to solve each captcha; the stall
    # threshold must exceed that so a captcha wait is not mistaken for a hang.
    stall_rounds = 24 if show_wait else STALL_ROUNDS

    if pkill:
        print("Killing existing CubeMini scrapers...")
        _ssh("pkill -f scrape_anjuke 2>/dev/null; sleep 2; echo done", timeout=10)

    slice_desc = f"offset {offset}, limit {limit}" if limit is not None else "all rows"
    print(f"\n🚀 CubeMini details crawl: region={region} ({slice_desc}, mode={'--show' if show_wait else '--xvfb'}) → {log}")

    for round_num in range(1, MAX_ROUNDS + 1):
        if _is_running():
            print(f"\n🔄 Round {round_num}/{MAX_ROUNDS}: crawler already running — monitoring, not launching a duplicate...")
        else:
            print(f"\n🔄 Round {round_num}/{MAX_ROUNDS}: launching...")
            launch(region, offset, limit, show_wait)

        time.sleep(POLL_SEC)
        last_line = ""
        stall = 0
        while stall < stall_rounds:
            out, _ = _ssh(f"tail -5 {log}", timeout=8)
            if any(m in out for m in DONE_MARKERS):
                print(f"  ✅ {region} complete!")
                print(out.strip())
                sys.exit(0)
            new_last = out.strip().split("\n")[-1] if out.strip() else ""
            if new_last == last_line:
                stall += 1
            else:
                stall = 0
                last_line = new_last
            # Progress summary
            for line in out.strip().split("\n")[-2:]:
                if "[Saved" in line or "[" in line and "/" in line:
                    print(f"  {line.strip()}")
            time.sleep(POLL_SEC)

        # Stalled — restart with same slice
        _ssh("pkill -f scrape_anjuke 2>/dev/null", timeout=5)
        print(f"  ⚠️  Stalled (no progress {stall_rounds * POLL_SEC}s) — restarting same slice...")

    print(f"\n❌ Max rounds ({MAX_ROUNDS}) reached. {region} partially complete.")
    sys.exit(2)


if __name__ == "__main__":
    main()
