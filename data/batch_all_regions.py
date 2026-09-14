"""Run detail enrichment for all regions, one at a time."""
import subprocess, sys, os

REGIONS_ORDER = [
    "chengdu_wuhou",       # 1213 left (161 done) — largest, most important district
    "chengdu_jinjiang",    # 725
    "chengdu_qingyang",    # 725
    "chengdu_chenghua",    # 725
    "chengdu_jinniu",      # 725
    "chengdu_gaoxin",      # 725
    "chengdu_shuangliu",   # 725
    "chengdu_dujiangyan",  # 725
    "chengdu_longquanyi",  # 725
    "chengdu_xindu",       # 725
    "chengdu_piduqu",      # 725
    "chengdu_wenjiang",    # 725
    "chengdu_tainfuxinqu",  # 724
    "chengdu_chongzhoushi", # 673
    "chengdu_pengzhoushi",  # 581
    "chengdu_xinjinxian",   # 495
    "chengdu_jintangxian",  # 478
    "chengdu_qingbaijiangqu", # 466
    "chengdu_dayixian",     # 454
    "chengdu_chengduzhoubian", # 400
    "chengdu_qionglaishi",  # 391
    "chengdu_cdjianyang",   # 250
    "chengdu_cdpujiangxian", # 172
    "yangling",             # 149
    "chengdu_gaoxinxiqu",   # 97
    "chengdu_dongbuxinqu",  # 59
    "datong_pingcheng",     # 725
]

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data/scrape_anjuke.py")

def run_region(rid: str):
    print(f"\n{'='*60}")
    print(f"REGION: {rid}")
    print(f"{'='*60}")
    result = subprocess.run(
        [sys.executable, SCRIPT, "--region", rid, "--details-only"],
        timeout=None,  # no timeout — let it finish naturally
    )
    return result.returncode

def main():
    failed = []
    for i, rid in enumerate(REGIONS_ORDER):
        print(f"\n[{i+1}/{len(REGIONS_ORDER)}] Starting {rid}...")
        rc = run_region(rid)
        if rc != 0:
            print(f"  WARNING: {rid} exited with code {rc}")
            failed.append(rid)
        else:
            print(f"  OK: {rid} complete")

    print(f"\n{'='*60}")
    print(f"DONE. {len(REGIONS_ORDER) - len(failed)}/{len(REGIONS_ORDER)} regions complete")
    if failed:
        print(f"FAILED: {failed}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
