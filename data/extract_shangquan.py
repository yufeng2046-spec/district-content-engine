"""
Extract 商圈 (sub-district commercial areas) from Anjuke for any city.
Reuses the same Playwright + stealth JS + cookie pattern as scrape_anjuke.py.

Usage:
    PYTHONPATH=. python3 data/extract_shangquan.py --city datong
    PYTHONPATH=. python3 data/extract_shangquan.py --city datong --login  (first time, solve captcha)
    PYTHONPATH=. python3 data/extract_shangquan.py --city xianyang --url https://xianyang.anjuke.com/community/

Output: data/shangquan_{city}.json
"""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import USER_AGENT

BASE_DIR = Path(__file__).resolve().parent.parent
COOKIES_FILE = BASE_DIR / "anjuke_cookies.json"

from data.scrapers.stealth import STEALTH_JS
from config import BAILIAN_KEY

# Import captcha solving from scrape_anjuke (shared VL-based solver)
from data.scrape_anjuke import auto_solve_captcha

# Default city → Anjuke community URL
CITY_URLS = {
    "datong": "https://datong.anjuke.com/community/",
    "xianyang": "https://xianyang.anjuke.com/community/",
    "baoji": "https://baoji.anjuke.com/community/",
    "chengdu": "https://chengdu.anjuke.com/community/",
    "beijing": "https://beijing.anjuke.com/community/",
}


async def _extract_district_links(page, base_url: str) -> list[dict]:
    """Extract all district (区/县) links from the main community page."""
    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    districts = await page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('.region-item a, a[href*="/community/"][href*="-q-"]').forEach(a => {
            const href = a.getAttribute('href');
            const text = a.textContent.trim().replace(/\\s+/g, ' ');
            if (href && text && text !== '不限' && text.length > 1 && text.length < 20) {
                // Only district-level links (not 商圈)
                const match = href.match(/\/community\/([a-z]+)\/$/);
                if (match && match[1] !== '') {
                    results.push({name: text, url: href, slug: match[1]});
                }
            }
        });
        // Also check filter-box
        document.querySelectorAll('.filter-box a[href*="/community/"]').forEach(a => {
            const href = a.getAttribute('href');
            const text = a.textContent.trim().replace(/\\s+/g, ' ');
            if (href && text && text !== '不限' && text.length > 1 && text.length < 20) {
                const match = href.match(/\/community\/([a-z]+)(\/)?$/);
                if (match && match[1] && !match[1].startsWith('p') && !match[1].startsWith('m') && !match[1].startsWith('f') && !match[1].startsWith('s') && !match[1].startsWith('o')) {
                    const exists = results.find(r => r.slug === match[1]);
                    if (!exists) results.push({name: text, url: href, slug: match[1]});
                }
            }
        });
        return results;
    }""")

    # Dedupe by slug
    seen = set()
    uniq = []
    for d in districts:
        if d["slug"] not in seen:
            seen.add(d["slug"])
            uniq.append(d)
    return uniq


async def _extract_shangquan_for_district(page, district_url: str) -> list[dict]:
    """Extract 商圈 links for a single district page."""
    try:
        await page.goto(district_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        await page.goto(district_url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(1500)

    sqs = await page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('a[href*="-q-"]').forEach(a => {
            const href = a.getAttribute('href');
            const text = a.textContent.trim().replace(/\\s+/g, ' ');
            if (text && text.length > 1 && text.length < 30 && href) {
                results.push({name: text, url: href});
            }
        });
        return results;
    }""")

    seen = set()
    uniq = []
    for s in sqs:
        if s["name"] not in seen:
            seen.add(s["name"])
            uniq.append(s)
    return uniq


async def extract_city(city: str, base_url: str, headless: bool = True, manual: bool = False) -> dict:
    """Extract all districts and their 商圈 for a city."""
    cookies = []
    if COOKIES_FILE.exists():
        cookies = json.loads(COOKIES_FILE.read_text())
        print(f"Loaded {len(cookies)} cookies")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        # Step 0: Navigate and handle captcha if present
        await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        title = await page.title()
        print(f"Page title: {title}")

        if "验证" in title or "验证码" in title:
            print("Captcha detected, attempting auto-solve...")
            if manual:
                print("  ⚠️  MANUAL MODE: Solve captcha in the visible browser window.")
                print("  Waiting for captcha to clear (polling every 3s, max 5 min)...")
                for _ in range(100):  # 5 minutes max
                    await page.wait_for_timeout(3000)
                    try:
                        t = await page.title()
                        if "验证" not in t and "验证码" not in t:
                            print(f"  ✓ Captcha appears solved (title: {t})")
                            break
                    except Exception:
                        pass
                else:
                    print("  ⚠️  Timeout waiting for captcha — continuing anyway...")
            elif BAILIAN_KEY:
                solved = await auto_solve_captcha(page, max_rounds=3)
                if solved:
                    print("  ✓ Captcha solved, re-navigating...")
                    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                else:
                    print("  ✗ Auto-solve failed. Try --login for manual solving.")
            else:
                print("  ✗ No BAILIAN_KEY set. Use --login for manual captcha solving.")
                print("    Set BAILIAN_KEY env var for auto VL-based captcha solving.")

        # Step 1: Get district list
        print(f"Fetching districts from {base_url}...")
        districts = await _extract_district_links(page, base_url)
        print(f"Found {len(districts)} districts: {[d['name'] for d in districts]}")

        # Step 2: For each district, get 商圈
        result = {"city": city, "base_url": base_url, "districts": {}}
        for d in districts:
            name = d["name"]
            url = d["url"]
            print(f"  Extracting 商圈 from {name}...")
            sqs = await _extract_shangquan_for_district(page, url)
            result["districts"][name] = {
                "url": url,
                "slug": d["slug"],
                "shangquan": sqs,
            }
            print(f"    → {len(sqs)} 商圈: {[s['name'] for s in sqs]}")

        # Save cookies for next time
        new_cookies = await context.cookies()
        COOKIES_FILE.write_text(json.dumps(new_cookies, ensure_ascii=False, indent=2))

        await browser.close()

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract 商圈 from Anjuke for any city")
    parser.add_argument("--city", required=True, help="City name (datong, xianyang, baoji...)")
    parser.add_argument("--url", help="Anjuke community base URL (auto-detected if not provided)")
    parser.add_argument("--login", action="store_true", help="Open visible browser to solve captcha")
    args = parser.parse_args()

    base_url = args.url or CITY_URLS.get(args.city)
    if not base_url:
        print(f"Error: Unknown city '{args.city}'. Provide --url or add to CITY_URLS in this script.")
        sys.exit(1)

    headless = not args.login
    if args.login:
        print("Opening visible browser — please solve the captcha if prompted.")

    result = asyncio.run(extract_city(args.city, base_url, headless=headless, manual=args.login))

    output_path = BASE_DIR / "data" / f"shangquan_{args.city}.json"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nSaved to {output_path}")
    print(f"Total districts: {len(result['districts'])}")
    total_sq = sum(len(v["shangquan"]) for v in result["districts"].values())
    print(f"Total 商圈: {total_sq}")


if __name__ == "__main__":
    main()
