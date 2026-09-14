# DEPRECATED (2026-07-23): Superseded by session_factory.py + sync_state_to_cubemini.py.
# The new architecture uses per-city state files and explicit city→IP routing
# instead of hardcoded city lists and SSH SOCKS tunnels. Kept for reference.
#!/usr/bin/env python3
"""
Dual-window launcher — runs two Anjuke scrapers in parallel:
  Window 1: Beijing IP (direct) → 北方城市
  Window 2: Zhangjiakou IP (SOCKS via CubeMini) → 南方城市

Usage:
    python3 dual_launcher.py
"""

import subprocess, json, sys, time, os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CUBEMINI_HOST = "cubemini"
SOCKS_PORT = 1080

# ── City assignments ──
# Format: (region_id, city_slug, shangquan_district_name)

BEIJING_CITIES = [
    # 华北
    "beijing_haidian",
    "beijing_chaoyang",
    # 东北 (省会优先)
    # "shenyang_heping", "dalian_zhongshan", "haerbin_nangang", "changchun_chaoyang",
    # 山东
    # "jinan_lixia", "qingdao_shinan",
]

ZHANGJIAKOU_CITIES = [
    # 西南
    "chengdu_qingyang",
    "chengdu_chenghua",
    "chengdu_jinniu",
    # 西北
    # "xa_yantaqu", "xa_beilinqu",
    # 华中 (省会)
    # "wuhan_wuchang", "zhengzhou_jinshui", "changsha_yuelu",
    # 华东 (上海江浙)
    # "shanghai_pudong", "nanjing_gulou", "hangzhou_xihu",
]


def start_scraper(region: str, proxy: str | None, label: str) -> subprocess.Popen:
    """Start a scrape_anjuke.py process for one region."""
    cmd = [
        sys.executable, "data/scrape_anjuke.py",
        "--region", region,
        "--shangquan", "all",
        "--show",
    ]
    if proxy:
        cmd.extend(["--proxy", proxy])

    print(f"[{label}] Starting: {' '.join(cmd)}")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BASE_DIR)

    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    print(f"[{label}] PID={proc.pid}")
    return proc


def main():
    print("=" * 60)
    print("Dual-Window Anjuke Crawler")
    print("=" * 60)

    # Start SOCKS proxy
    print("\n[Setup] Starting SOCKS proxy to CubeMini...")
    subprocess.run(
        ["ssh", "-i", str(Path.home() / ".ssh/id_ed25519_cubemini"),
         "-D", str(SOCKS_PORT), "-N", "-f", CUBEMINI_HOST],
        check=False
    )
    time.sleep(2)
    print(f"  SOCKS proxy on :{SOCKS_PORT}")

    proxy_url = f"socks5://127.0.0.1:{SOCKS_PORT}"

    # Process cities one at a time, alternating between windows
    beijing_idx = 0
    zhangjiakou_idx = 0

    while beijing_idx < len(BEIJING_CITIES) or zhangjiakou_idx < len(ZHANGJIAKOU_CITIES):
        # Start Beijing scraper if available
        beijing_proc = None
        if beijing_idx < len(BEIJING_CITIES):
            region = BEIJING_CITIES[beijing_idx]
            beijing_proc = start_scraper(region, None, f"BJ-{region}")
            beijing_idx += 1

        # Start Zhangjiakou scraper if available
        zjk_proc = None
        if zhangjiakou_idx < len(ZHANGJIAKOU_CITIES):
            region = ZHANGJIAKOU_CITIES[zhangjiakou_idx]
            zjk_proc = start_scraper(region, proxy_url, f"ZJK-{region}")
            zhangjiakou_idx += 1

        # Wait for both to complete
        procs = [p for p in [beijing_proc, zjk_proc] if p is not None]
        print(f"\n  Running {len(procs)} scraper(s)...")

        for proc in procs:
            stdout, _ = proc.communicate()
            exit_code = proc.returncode
            # Print last few lines
            lines = stdout.strip().split('\n') if stdout else []
            for line in lines[-5:]:
                print(f"    {line}")
            print(f"  Exit: {exit_code}")

    print("\n" + "=" * 60)
    print("All cities complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
