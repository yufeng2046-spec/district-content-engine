#!/usr/bin/env python3
"""Pull a region's crawled results from CubeMini and merge into local DB.

Run on the local Mac (keeps the local DB authoritative). Steps:
  1. On CubeMini: export the region's rows that have detail_scraped_at set.
  2. SFTP-pull the transfer file.
  3. merge_detail into the local DB (updates detail columns only; preserves
     local metadata region_id/shangquan_id/name/address/...).
  4. Report counts.

Usage:
    python3 merge_from_cubemini.py <region_id> [--no-validate]

Example:
    python3 merge_from_cubemini.py shenzhen
"""
from __future__ import annotations

import base64
import sqlite3
import sys
import time

from sync_state_to_cubemini import ssh_exec, ssh_sftp_get
from db.dbtransfer import import_communities

CUBE_DB = "/home/frank/district-content-engine/district_content.db"


def retry(fn, tries: int = 4, delay: float = 6):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            print(f"  [retry {i + 1}] {str(e)[:120]}")
            time.sleep(delay)
    raise RuntimeError("retries exhausted")


def cube_export(region: str) -> int:
    script = (f"import sys; sys.path.insert(0,'/home/frank/district-content-engine');"
              f"from db.dbtransfer import export_communities;"
              f"n=export_communities('{CUBE_DB}','/tmp/cube_{region}_done.db',"
              f" region_id='{region}', detail_only=True);"
              f"print('exported',n)")
    b64 = base64.b64encode(script.encode()).decode()
    out, err = retry(lambda: ssh_exec(
        f"echo {b64} | base64 -d | /home/frank/crawler-venv/bin/python3", timeout=120))
    print(f"  CubeMini: {out.strip()}")
    if err:
        print(f"  STDERR: {err[:300]}")
    return int(out.strip().split()[-1]) if out.strip() else 0


def main():
    region = sys.argv[1] if len(sys.argv) > 1 else "shenzhen"
    no_validate = "--no-validate" in sys.argv

    print(f"=== Pull {region} from CubeMini → merge → local ===")
    before = sqlite3.connect("district_content.db").execute(
        "SELECT COUNT(*) FROM communities WHERE region_id=? AND detail_scraped_at IS NOT NULL",
        (region,)).fetchone()[0]

    n_export = cube_export(region)
    if n_export == 0:
        print("  No done rows on CubeMini — nothing to merge.")
        return

    retry(lambda: ssh_sftp_get(f"/tmp/cube_{region}_done.db", f"/tmp/cube_{region}_done.db"))
    n_merge = import_communities("district_content.db", f"/tmp/cube_{region}_done.db",
                                 mode="merge_detail",
                                 predicate="detail_scraped_at IS NOT NULL")
    after = sqlite3.connect("district_content.db").execute(
        "SELECT COUNT(*) FROM communities WHERE region_id=? AND detail_scraped_at IS NOT NULL",
        (region,)).fetchone()[0]
    print(f"  merged {n_merge} rows | local {region} with detail: {before} → {after}")

    if not no_validate:
        import subprocess
        subprocess.run([sys.executable, "validate.py"], capture_output=False)
        subprocess.run([sys.executable, "check_crawl.py", "--region", region], capture_output=False)


if __name__ == "__main__":
    main()
