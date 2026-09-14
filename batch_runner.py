# DEPRECATED (2026-07-23): Use data/scrape_anjuke.py --region ID --shangquan all --show directly.
# Thin wrapper superseded by native batch mode. Kept for reference.
#!/usr/bin/env python3
"""
Long-session batch runner — opens one browser window, processes multiple
districts sequentially, keeping the session alive. Only needs ONE captcha
solve at the start.

Usage:
    # Beijing IP (direct)
    PYTHONPATH=. python3 batch_runner.py

    # Zhangjiakou IP (via CubeMini SOCKS proxy)
    PYTHONPATH=. python3 batch_runner.py --proxy socks5://127.0.0.1:1080
"""

import asyncio, json, random, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.async_api import async_playwright
from config import USER_AGENT
from db.schema import create_tables
from data.scrapers.stealth import STEALTH_JS
from data.scrape_anjuke import scrape_all_shangquan

BASE_DIR = Path(__file__).resolve().parent

# ── Districts to process ──
# Each: (region_id, city_slug, district_name)
DISTRICTS = [
    ("chengdu_wenjiang", "chengdu", "温江"),
]


async def main():
    proxy = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--proxy" and i + 1 < len(args):
            proxy = args[i + 1]; i += 2
        else:
            i += 1

    create_tables()

    browser_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    if proxy:
        browser_args.append(f"--proxy-server={proxy}")
        print(f"Proxy: {proxy}")

    print("=" * 60)
    print(f"Batch Runner — {len(DISTRICTS)} districts, single session")
    print("=" * 60)
    print("\n⚠️  Browser window opening — solve the first captcha when it appears")
    print("   After that, the session stays warm for all districts.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=browser_args,
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        for idx, (region_id, city_slug, district_name) in enumerate(DISTRICTS):
            print(f"\n{'='*60}")
            print(f"[{idx+1}/{len(DISTRICTS)}] {district_name} ({region_id})")
            print(f"{'='*60}")

            try:
                total, saved = await scrape_all_shangquan(
                    page, region_id, city_slug, district_name,
                    max_communities=0, show_browser=True
                )
                print(f"  Result: scraped {total}, saved {saved}")
            except Exception as e:
                print(f"  Error: {e}")

            # Cooldown between districts
            if idx < len(DISTRICTS) - 1:
                delay = random.randint(30, 60)
                print(f"  Cooldown: {delay}s...")
                await asyncio.sleep(delay)

        await browser.close()

    print(f"\n{'='*60}")
    print("Batch complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
