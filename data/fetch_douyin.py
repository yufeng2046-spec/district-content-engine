"""
Fetch Yangling-related real estate content from Douyin search API.
Extracts local voices: what locals are saying, complaints, price sentiment, community mentions.

Usage:
    PYTHONPATH=. python3 data/fetch_douyin.py              # search all 8 keywords
    PYTHONPATH=. python3 data/fetch_douyin.py --max 3      # search first 3 keywords
    PYTHONPATH=. python3 data/fetch_douyin.py --refresh    # force re-fetch (ignore cache)
"""

import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DOUYIN_KEYWORDS, USER_AGENT, REGION_NAME

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_FILE = BASE_DIR / "data" / "douyin_content.json"

# Cookie source: shared with competitor-report
COOKIE_CANDIDATES = [
    Path("/Users/m/claude-workspace/competitor-report/douyin_cookies.json"),
    Path("/Users/m/claude-workspace/competitor-report/cookies.json"),
]

RESULTS_PER_KEYWORD = 20
SEARCH_DELAY_S = 3  # Between keyword searches


def load_cookies() -> list[dict]:
    for path in COOKIE_CANDIDATES:
        if path.exists():
            return json.loads(path.read_text())
    return []


SEARCH_JS = """async (keyword) => {
    const params = new URLSearchParams({
        device_platform: 'webapp', aid: '6383', channel: 'channel_pc_web',
        keyword: keyword, count: '20', cookie_enabled: 'true',
        platform: 'PC', search_source: 'normal_search',
    });
    const url = '/aweme/v1/web/search/item/?' + params.toString();

    const headers = {};
    if (window.byted_acrawler?.frontierSign) {
        const r = window.byted_acrawler.frontierSign({ url, method: 'GET' });
        if (r?.['X-Bogus']) headers['X-Bogus'] = r['X-Bogus'];
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    try {
        const resp = await fetch(url, {
            credentials: 'include', headers, signal: controller.signal
        });
        clearTimeout(timeout);
        const text = await resp.text();
        if (!text || text.length < 10) return [];
        const data = JSON.parse(text);
        return (data.data || []).map(item => {
            const aweme = item.aweme_info || {};
            return {
                desc: aweme.desc || '',
                author: (aweme.author || {}).nickname || '',
                create_time: aweme.create_time || 0,
                digg_count: (aweme.statistics || {}).digg_count || 0,
                comment_count: (aweme.statistics || {}).comment_count || 0,
                share_count: (aweme.statistics || {}).share_count || 0,
            };
        });
    } catch(e) {
        return [];
    }
}"""


def classify_content(desc: str) -> str:
    """Classify a Douyin description into content type."""
    complaint_kw = ["坑", "后悔", "千万别", "避坑", "踩坑", "烂尾", "维权", "黑心",
                    "不要买", "别买", "套路", "骗", "差", "问题", "投诉", "曝光"]
    price_kw = ["均价", "一平", "元/平", "元/㎡", "降价", "涨价", "总价", "首付", "月供"]
    community_kw = ["小区", "探盘", "看房", "实拍", "实探", "踩盘"]

    if any(kw in desc for kw in complaint_kw):
        return "complaint"
    if any(kw in desc for kw in community_kw):
        return "community_mention"
    if any(kw in desc for kw in price_kw):
        return "price_talk"
    return "general"


def extract_mentions(desc: str) -> list[str]:
    """Extract community names mentioned in description."""
    patterns = [
        r'(?:杨凌|杨陵)?([一-鿿]{2,4}(?:小区|苑|园|城|庭|居|府|庄|寓|邸|郡|堡))',
        r'(?:杨凌|杨陵)?([一-鿿]{2,3}(?:花园|华庭|家园|新城|新村|国际|广场|山庄|雅苑|名都|华府|景苑|嘉苑|名邸))',
        r'(?:杨凌|杨陵)?([一-鿿]{2,6}(?:和府|华庭|华城|景城|星城|学府|公馆|墅|湾|筑|境))',
        r'([一-鿿]{3,4}(?:名城|新都|花城|世纪城|锦城|尚都|豪庭|雅居|香郡|水岸|湖畔|绿洲|春居))',
    ]
    mentions = set()
    for pat in patterns:
        mentions.update(re.findall(pat, desc))
    # Filter out false positives (too short, or known non-community words)
    false_positives = {"小区", "苑", "园", "城", "庭", "居", "府", "庄", "寓", "邸", "郡", "堡",
                       "花园", "华庭", "家园", "新城", "新村", "国际", "广场", "山庄", "雅苑", "名都"}
    return [m for m in mentions if m not in false_positives and len(m) >= 3]


async def fetch_keywords(keywords: list[str], headless: bool = True) -> list[dict]:
    """Search Douyin for each keyword, return deduplicated results."""
    cookies = load_cookies()
    if not cookies:
        print("ERROR: No Douyin cookies found. Run competitor-report login first.")
        return []

    all_results = []
    seen_descs = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        # Establish session
        print("Establishing Douyin session...")
        try:
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
        except Exception:
            print("  (timeout on main page, proceeding with API)")
        await page.wait_for_timeout(3000)

        page_title = await page.title()
        if "验证" in page_title:
            print("CAPTCHA detected. Try running with --show and solve manually.")
            await browser.close()
            return []

        for i, kw in enumerate(keywords):
            print(f"\n[{i+1}/{len(keywords)}] Searching: {kw}")
            try:
                results = await page.evaluate(SEARCH_JS, kw)
            except Exception as e:
                print(f"  API error: {e}")
                results = []

            new_count = 0
            for item in results:
                desc = item.get("desc", "").strip()
                if not desc or desc in seen_descs:
                    continue
                seen_descs.add(desc)

                mention_type = classify_content(desc)
                communities = extract_mentions(desc)

                all_results.append({
                    "desc": desc,
                    "author": item["author"],
                    "type": mention_type,
                    "communities_mentioned": communities,
                    "digg_count": item["digg_count"],
                    "comment_count": item["comment_count"],
                    "keyword": kw,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                new_count += 1

            print(f"  -> {new_count} new results (total: {len(all_results)})")

            if i < len(keywords) - 1:
                await page.wait_for_timeout(SEARCH_DELAY_S * 1000)

        await browser.close()

    return all_results


def save_results(results: list[dict]) -> dict:
    """Save to JSON and return summary stats."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Build summary
    type_counts = {}
    all_communities = set()
    for r in results:
        type_counts[r["type"]] = type_counts.get(r["type"], 0) + 1
        all_communities.update(r["communities_mentioned"])

    summary = {
        "total_results": len(results),
        "keywords_searched": len(DOUYIN_KEYWORDS),
        "type_breakdown": type_counts,
        "communities_mentioned": sorted(all_communities),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "region": REGION_NAME,
    }

    output = {
        "summary": summary,
        "results": results,
    }

    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nSaved {len(results)} results to {OUTPUT_FILE}")
    return summary


def load_cached():
    """Load cached Douyin content if available."""
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def main():
    args = sys.argv[1:]
    max_keywords = len(DOUYIN_KEYWORDS)
    force_refresh = False
    show_browser = False

    i = 0
    while i < len(args):
        if args[i] == "--max" and i + 1 < len(args):
            max_keywords = int(args[i + 1]); i += 2
        elif args[i] == "--refresh":
            force_refresh = True; i += 1
        elif args[i] == "--show":
            show_browser = True; i += 1
        else:
            i += 1

    if not force_refresh:
        cached = load_cached()
        if cached and cached.get("summary", {}).get("total_results", 0) > 0:
            s = cached["summary"]
            print(f"Cached Douyin content available ({s['total_results']} results from {s.get('fetched_at', 'unknown')})")
            print(f"  Type breakdown: {s.get('type_breakdown', {})}")
            print(f"  Communities mentioned: {s.get('communities_mentioned', [])}")
            print(f"  Use --refresh to re-fetch.")
            return

    keywords = DOUYIN_KEYWORDS[:max_keywords]
    print(f"Douyin Local Content Fetcher — {REGION_NAME}")
    print(f"  Keywords: {len(keywords)}")
    print(f"  Output: {OUTPUT_FILE}")
    print()

    results = asyncio.run(fetch_keywords(keywords, headless=not show_browser))
    if not results:
        print("\nNo results fetched.")
        return

    summary = save_results(results)
    print(f"\nSummary:")
    print(f"  Total results: {summary['total_results']}")
    print(f"  Types: {summary['type_breakdown']}")
    print(f"  Communities mentioned: {len(summary['communities_mentioned'])}")
    for c in summary['communities_mentioned'][:20]:
        print(f"    - {c}")


if __name__ == "__main__":
    main()
