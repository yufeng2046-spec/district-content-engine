"""
Batch scrape all Xi'an regions in one Chrome session.
Uses --shangquan all mode: listing + detail in one pass per region.

Usage:
    PYTHONPATH=. python3 data/batch_xian.py
"""

import asyncio, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright
from config import BAILIAN_KEY
from db.schema import create_tables
from data.scrapers.stealth import STEALTH_JS
from data.scrape_anjuke import scrape_all_shangquan

CHROME_PROFILE = Path(__file__).resolve().parent.parent / "chrome_profile_v2"


async def main():
    create_tables()

    # Xi'an regions in priority order (by estimated size)
    # Skip weiyangq if it's nearly done
    regions = [
        ("xa_yantaqu", "雁塔"),
        ("xa_gaoxinxa", "高新"),
        ("xa_beilinqu", "碑林"),
        ("xa_lianhuqu", "莲湖"),
        ("xa_qujiangxinqu", "曲江新区"),
        ("xa_xinchengqu", "新城"),
        ("xa_jingkaiqux", "经开区"),
        ("xa_weiyangq", "未央"),  # Has 196 remaining with details
    ]

    print("=" * 60)
    print("Xi'an Batch — All Regions in One Chrome Session")
    print("=" * 60)
    print(f"Regions: {len(regions)}")
    for rid, label in regions:
        print(f"  - {label} ({rid})")

    # Kill stale Chrome
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

        t_start = time.time()

        for idx, (region_id, label) in enumerate(regions):
            print(f"\n{'='*60}")
            print(f"[{idx+1}/{len(regions)}] Xi'an {label} ({region_id})")
            print(f"{'='*60}")

            city_slug = "xa"  # Xi'an Anjuke subdomain
            district_name = label  # Chinese name for filtering shangquan

            try:
                total_scraped, total_saved = await scrape_all_shangquan(
                    page, region_id, city_slug, district_name,
                    max_communities=0, show_browser=True
                )
                print(f"\n  {label}: scraped {total_scraped}, saved {total_saved}")
            except Exception as e:
                print(f"\n  Error in {label}: {e}")
                import traceback
                traceback.print_exc()

            # Save state between regions
            try:
                _state = await context.storage_state()
                _state_file.write_text(json.dumps(_state))
            except Exception:
                pass

            # Cooldown between regions
            if idx < len(regions) - 1:
                delay = 15 + (idx % 5) * 3  # 15-30s
                print(f"\n  ⏳ Cooldown: {delay}s...")
                await page.wait_for_timeout(delay * 1000)

        # Final state save
        try:
            _state = await context.storage_state()
            _state_file.write_text(json.dumps(_state))
        except Exception:
            pass

        await browser.close()

    elapsed = (time.time() - t_start) / 60
    print(f"\n{'='*60}")
    print(f"Xi'an all done in {elapsed:.0f} min")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
