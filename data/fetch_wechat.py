"""
Fetch Yangling real estate articles from Sogou WeChat Search via Playwright.
Extracts: article title, account name, publish date, full text.
Used for city/district-level context and opinion data in research briefs.

Usage:
    PYTHONPATH=. python3 data/fetch_wechat.py              # search all keywords
    PYTHONPATH=. python3 data/fetch_wechat.py --max 3      # search first 3 keywords
    PYTHONPATH=. python3 data/fetch_wechat.py --refresh    # force re-fetch (ignore cache)
"""

import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import USER_AGENT, REGION_NAME, REGION_ID

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_FILE = BASE_DIR / "data" / "wechat_content.json"

# Keywords for city/district-level context.
# Use both 杨凌 and 杨陵区 (both spellings are common locally).
# Quoted phrases and specific terms reduce noise from broad Sogou matching.
WECHAT_KEYWORDS = [
    # 房产类（原有）
    "杨凌 买房",
    "杨凌 楼盘 新房",
    "杨凌 房价 走势",
    "杨凌 房产 市场",
    "杨凌 城市规划",
    "杨凌 区域 发展",
    # 经济产业
    "杨凌 经济 产业",
    "杨凌 农业 科技 示范",
    "杨凌 企业 产业 园区",
    # 城市定位 / 核心IP
    "杨凌 农高会",
    "杨凌 上合 农业 组织",
    "杨凌 自贸 保税",
    # 高校人才
    "西北农林科技大学 杨凌",
    "杨凌 人才 落户 政策",
    # 交通基建
    "杨凌 高铁 交通 规划",
    # 医疗商业
    "杨凌 医院 医疗",
    "杨凌 万达 商业 配套",
    # 生活宜居
    "杨凌 生活 环境 宜居",
    "杨凌 人口 发展",
]

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
"""


def load_cache() -> dict:
    """Load existing cache keyed by article URL."""
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    OUTPUT_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_timestamps(html: str) -> list[str]:
    """Extract and convert Unix timestamps from Sogou HTML."""
    stamps = re.findall(r"timeConvert\('(\d+)'\)", html)
    return [datetime.fromtimestamp(int(s)).strftime("%Y-%m-%d") for s in stamps]


async def search_wechat(page, query: str) -> list:
    """Search Sogou WeChat for a keyword and return results with titles, links, summaries."""
    encoded = query.replace(" ", "+")
    url = f"https://weixin.sogou.com/weixin?type=2&query={encoded}&ie=utf8"
    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(2500)

    html_content = await page.content()
    times = parse_timestamps(html_content)

    results = await page.evaluate("""
        () => {
            const items = [];
            document.querySelectorAll('li[id*="sogou_vr_11002601_box_"]').forEach(function(li) {
                const titleEl = li.querySelector('a[id*="title_"]');
                const title = titleEl ? titleEl.textContent.trim() : '';
                const href = titleEl ? titleEl.getAttribute('href') : '';
                const txtBox = li.querySelector('.txt-box');
                const summary = txtBox ? (txtBox.querySelector('p') ? txtBox.querySelector('p').textContent.trim() : '') : '';
                const sp = txtBox ? txtBox.querySelector('.s-p') : null;
                const sourceEl = sp ? sp.querySelector('a') : null;
                const source = sourceEl ? sourceEl.textContent.trim() : '';
                if (title) {
                    items.push({title: title, href: href, summary: summary, source: source});
                }
            });
            return items;
        }
    """)

    # Filter: only keep articles relevant to the target region
    region_terms = ["杨凌", "杨陵", "咸阳", "西农", "示范"]
    exclude_terms = ["招聘", "相亲", "求职", "入学", "招生", "报名", "幼儿园"]
    relevant = []
    for i, r in enumerate(results):
        combined = r["title"] + r.get("summary", "")
        if not any(term in combined for term in region_terms):
            continue
        if any(term in combined for term in exclude_terms):
            continue
        r["publish_time"] = times[i] if i < len(times) else ""
        r["query"] = query
        r["_dom_index"] = i  # track original DOM position for click extraction
        relevant.append(r)

    return relevant


async def extract_article_text(page, result_index: int) -> Optional[dict]:
    """Click a search result and extract full article text from the popup."""
    selector = f'a[id*="sogou_vr_11002601_title_{result_index}"]'
    link_el = await page.query_selector(selector)
    if not link_el:
        return None

    try:
        async with page.expect_popup(timeout=30000) as popup_info:
            await link_el.click()
        popup = await popup_info.value
        await popup.wait_for_load_state("networkidle", timeout=30000)
        await popup.wait_for_timeout(2000)

        if "mp.weixin.qq.com" not in popup.url:
            await popup.close()
            return None

        text = await popup.evaluate("""
            () => {
                var el = document.getElementById('js_content');
                return el ? el.innerText : '';
            }
        """)

        meta = await popup.evaluate("""
            () => {
                var name = document.querySelector('#js_name');
                var date = document.querySelector('#publish_time');
                var title = document.querySelector('#activity-name');
                return {
                    account: name ? name.textContent.trim() : '',
                    date: date ? date.textContent.trim() : '',
                    title: title ? title.textContent.trim() : ''
                };
            }
        """)

        real_url = popup.url
        await popup.close()
        return {"text": text.strip(), "url": real_url, **meta}

    except Exception as e:
        print(f"    ⚠️  Popup error: {e}")
        return None


async def main():
    refresh = "--refresh" in sys.argv
    max_kw = None
    for i, arg in enumerate(sys.argv):
        if arg == "--max" and i + 1 < len(sys.argv):
            max_kw = int(sys.argv[i + 1])

    keywords = WECHAT_KEYWORDS[:max_kw] if max_kw else WECHAT_KEYWORDS
    cache = {} if refresh else load_cache()
    new_articles = 0

    print(f"WeChat article search — {len(keywords)} keywords")
    print(f"Cache: {len(cache)} existing articles\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            user_agent=USER_AGENT,
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        # Prime cookies by visiting sogou.com first
        await page.goto("https://www.sogou.com/", wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(1500)

        for kw_idx, query in enumerate(keywords):
            print(f"[{kw_idx + 1}/{len(keywords)}] {query}")

            results = await search_wechat(page, query)
            print(f"  Found {len(results)} results")

            for i, r in enumerate(results):
                title = r["title"]
                if title in cache:
                    continue

                # Rate limit: 3s between article fetches
                await page.wait_for_timeout(3000)

                dom_idx = r.get("_dom_index", i)
                full = await extract_article_text(page, dom_idx)
                if not full:
                    print(f"    [{i}] {title[:50]}... — skip (no content)")
                    continue

                article = {
                    "title": full.get("title") or title,
                    "account": full.get("account", r.get("source", "")),
                    "publish_time": full.get("date") or r.get("publish_time", ""),
                    "url": full["url"],
                    "text": full["text"],
                    "query": query,
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }

                # Use URL as cache key for dedup
                cache_key = full["url"] or title
                cache[cache_key] = article
                new_articles += 1
                print(f"    [{i}] {article['title'][:50]}... — {len(full['text'])} chars ✓")

            # Save incrementally after each keyword
            save_cache(cache)

        await browser.close()

    print(f"\nDone. {new_articles} new articles, {len(cache)} total in cache")
    print(f"Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
