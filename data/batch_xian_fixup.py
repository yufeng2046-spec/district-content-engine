"""
Fixup Xi'an — re-run failed/missing regions + fill gaps.
Targeted approach: only regions that need work.

Usage:
    PYTHONPATH=. python3 data/batch_xian_fixup.py
"""

import asyncio, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright
from config import BAILIAN_KEY
from db.schema import create_tables
from data.scrapers.stealth import STEALTH_JS
from data.scrape_anjuke import scrape_all_shangquan, scrape_detail, load_communities_from_db, save_to_db

CHROME_PROFILE = Path(__file__).resolve().parent.parent / "chrome_profile_v2"
DETAIL_DELAY_MIN_MS = 3000
DETAIL_DELAY_MAX_MS = 5000


async def main():
    create_tables()

    # Round 1: Missing regions (listing + detail)
    regions_full = [
        ("xa_gaoxinxa", "高新区"),       # Fixed: was "高新"
        ("xa_qujiangxinqu", "曲江新区"),
        ("xa_jingkaiqux", "经开区"),
    ]

    # Round 2: Detail-only for regions with listings but missing details
    regions_detail_only = [
        ("xa_weiyangq", "未央"),
        ("xa_lianhuqu", "莲湖"),
        ("xa_yantaqu", "雁塔"),
        ("xa_beilinqu", "碑林"),
        ("xa_xinchengqu", "新城"),
    ]

    print("=" * 60)
    print("Xi'an Fixup — Targeted Rescrape")
    print("=" * 60)
    print(f"Full scrape (3 regions): {[r[1] for r in regions_full]}")
    print(f"Detail-only (5 regions): {[r[1] for r in regions_detail_only]}")

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

        # ── Round 1: Full scrape ──
        for idx, (region_id, label) in enumerate(regions_full):
            print(f"\n{'='*60}")
            print(f"[Full {idx+1}/{len(regions_full)}] {label} ({region_id})")
            print(f"{'='*60}")

            try:
                total_scraped, total_saved = await scrape_all_shangquan(
                    page, region_id, "xa", label,
                    max_communities=0, show_browser=True
                )
                print(f"  {label}: scraped {total_scraped}, saved {total_saved}")
            except Exception as e:
                print(f"  Error in {label}: {e}")

            # Save state
            try:
                _state = await context.storage_state()
                _state_file.write_text(json.dumps(_state))
            except Exception:
                pass

            if idx < len(regions_full) - 1:
                delay = random.randint(15, 30)
                print(f"  ⏳ Cooldown: {delay}s...")
                await page.wait_for_timeout(delay * 1000)

        # ── Round 2: Detail-only ──
        for idx, (region_id, label) in enumerate(regions_detail_only):
            communities = load_communities_from_db(region_id, missing_only=True)
            if not communities:
                print(f"\n  {label}: all details done, skip")
                continue

            print(f"\n{'='*60}")
            print(f"[Detail {idx+1}/{len(regions_detail_only)}] {label} ({region_id})")
            print(f"{'='*60}")
            print(f"  {len(communities)} communities missing details")

            saved = 0
            for i, c in enumerate(communities):
                # Skip communities without valid URL
                if not c.get("url"):
                    continue

                try:
                    result = await scrape_detail(page, c, show_browser=True)
                    communities[i] = result
                    delay_s = random.randint(DETAIL_DELAY_MIN_MS, DETAIL_DELAY_MAX_MS) / 1000
                    await page.wait_for_timeout(int(delay_s * 1000))

                    if (i > 0 and i % 10 == 0) or i == len(communities) - 1:
                        saved = save_to_db(communities[:i + 1], region_id)
                        print(f"    [Saved {saved}/{len(communities)}]")
                except Exception as e:
                    print(f"    Detail error for {c.get('name','?')}: {e}")
                    continue

            # Final save
            saved = save_to_db(communities, region_id)
            print(f"  {label}: {saved}/{len(communities)} saved")

            if idx < len(regions_detail_only) - 1:
                delay = random.randint(10, 20)
                print(f"  ⏳ Cooldown: {delay}s...")
                await page.wait_for_timeout(delay * 1000)

        # Save final state
        try:
            _state = await context.storage_state()
            _state_file.write_text(json.dumps(_state))
        except Exception:
            pass

        await browser.close()

    elapsed = (time.time() - t_start) / 60
    print(f"\n{'='*60}")
    print(f"Xi'an fixup done in {elapsed:.0f} min")
    print(f"{'='*60}")


if __name__ == "__main__":
    import random
    asyncio.run(main())
