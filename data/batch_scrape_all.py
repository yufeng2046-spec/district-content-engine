"""
Batch scrape all remaining Chengdu + Xi'an details in ONE session.
Avoids Chrome launch/teardown instability between regions.

Usage:
    PYTHONPATH=. python3 data/batch_scrape_all.py
"""

import asyncio, json, random, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright
from config import USER_AGENT, DETAIL_DELAY_MIN_MS, DETAIL_DELAY_MAX_MS
from data.scrapers.stealth import STEALTH_JS
from db.connection import get_db
from db.schema import create_tables
from data.scrape_anjuke import scrape_detail, scrape_listing_page, save_to_db, load_communities_from_db

CHROME_PROFILE = Path(__file__).resolve().parent.parent / "chrome_profile"


async def scrape_region(page, region_id: str, label: str):
    """Scrape all missing details for one region."""
    communities = load_communities_from_db(region_id, missing_only=True)
    if not communities:
        print(f"  {label}: all done!")
        return 0

    total = len(communities)
    print(f"\n{'='*50}")
    print(f"  {label} ({region_id}): {total} missing details")
    print(f"{'='*50}")

    saved = 0
    for i, c in enumerate(communities):
        print(f"\n  [{i+1}/{total}] {c['name']}")
        try:
            result = await scrape_detail(page, c, show_browser=True)
            communities[i] = result

            delay_s = random.uniform(DETAIL_DELAY_MIN_MS, DETAIL_DELAY_MAX_MS) / 1000
            await page.wait_for_timeout(int(delay_s * 1000))

            if (i > 0 and i % 10 == 0) or i == total - 1:
                saved = save_to_db(communities[:i + 1], region_id)
                print(f"    [Saved {saved}/{total}]")
        except Exception as e:
            print(f"    Error: {e}")
            continue

    # Final save
    saved = save_to_db(communities, region_id)
    print(f"  {label}: {saved}/{total} saved")
    return saved


async def main():
    create_tables()

    # Regions to scrape — Yangling first (298 missing), then Chengdu by gap size
    tasks = [
        ("yangling", "杨凌"),
        ("chengdu_chengduzhoubian", "成都周边"),
        ("chengdu_longquanyi", "成都龙泉驿"),
        ("chengdu_pengzhoushi", "成都彭州"),
        ("chengdu_qingbaijiangqu", "成都青白江"),
        ("chengdu_chongzhoushi", "成都崇州"),
        ("chengdu_jintangxian", "成都金堂"),
        ("chengdu_shuangliu", "成都双流"),
        ("chengdu_jinjiang", "成都锦江"),
        ("chengdu_wenjiang", "成都温江"),
        ("chengdu_cdjianyang", "成都简阳"),
        ("chengdu_dayixian", "成都大邑"),
        ("chengdu_piduqu", "成都郫都"),
        ("chengdu_xindu", "成都新都"),
    ]

    print("=" * 60)
    print("Batch Scrape All — Single Chrome Session")
    print("=" * 60)

    # Kill any existing Chrome using our profile
    import subprocess
    subprocess.run(["pkill", "-f", "chrome_profile"], capture_output=True)
    time.sleep(2)
    _lock = CHROME_PROFILE / "SingletonLock"
    if _lock.exists():
        try:
            _lock.unlink()
        except Exception:
            pass

    async with async_playwright() as p:
        # Launch ONE Chrome for the entire batch
        browser = await p.chromium.launch(
            channel='chrome',
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        _state_file = CHROME_PROFILE / "state.json"
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            storage_state=str(_state_file) if _state_file.exists() else None,
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        total_saved = 0
        t_start = time.time()

        for region_id, label in tasks:
            saved = await scrape_region(page, region_id, label)
            total_saved += saved

            # Save state after each region
            try:
                _state = await context.storage_state()
                _state_file.write_text(json.dumps(_state))
            except Exception:
                pass

        # Save final state
        try:
            _state = await context.storage_state()
            _state_file.write_text(json.dumps(_state))
        except Exception:
            pass

        await browser.close()

    elapsed = (time.time() - t_start) / 60
    print(f"\n{'='*60}")
    print(f"All done: {total_saved} details over {elapsed:.0f} min")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
