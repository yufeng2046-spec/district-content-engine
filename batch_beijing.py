# DEPRECATED (2026-07-23): Use data/scrape_anjuke.py --region ID --shangquan all --show directly.
# Thin wrapper superseded by native batch mode. Kept for reference.
#!/usr/bin/env python3
"""Beijing IP direct window — 5 Chengdu districts at district-level cap (725)."""
import asyncio, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.async_api import async_playwright
from config import USER_AGENT
from db.schema import create_tables
from data.scrapers.stealth import STEALTH_JS
from data.scrape_anjuke import scrape_all_shangquan

DISTRICTS = [
    ("chengdu_piduqu", "chengdu", "郫都"),
]

async def main():
    create_tables()
    print("=" * 60)
    print(f"Beijing IP Batch — {len(DISTRICTS)} districts")
    print("=" * 60)
    print("\n⚠️  Browser opening — solve the captcha when it appears\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
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
            if idx < len(DISTRICTS) - 1:
                delay = random.randint(30, 60)
                print(f"  Cooldown: {delay}s...")
                await asyncio.sleep(delay)
        await browser.close()
    print(f"\n{'='*60}\nBeijing IP batch complete!\n{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
