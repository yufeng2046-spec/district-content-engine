"""
Fetch real estate articles from Sogou WeChat Search via Playwright.
Extracts: article title, account name, publish date, full text.
Used for city/district-level context and opinion data in research briefs.

Usage:
    PYTHONPATH=. python3 data/fetch_wechat.py                          # default region
    PYTHONPATH=. python3 data/fetch_wechat.py --region datong_pingcheng
    PYTHONPATH=. python3 data/fetch_wechat.py --region datong_pingcheng --max 3
    PYTHONPATH=. python3 data/fetch_wechat.py --region datong_pingcheng --refresh
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
from config import USER_AGENT, get_region, DEFAULT_REGION, REGIONS
from db.connection import get_db
from db.schema import create_tables

BASE_DIR = Path(__file__).resolve().parent.parent

from data.scrapers.stealth import STEALTH_JS


def load_cache(output_file: Path) -> dict:
    """Load existing cache keyed by article URL."""
    if output_file.exists():
        return json.loads(output_file.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict, output_file: Path) -> None:
    output_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def save_wechat_to_db(cache: dict, region_id: str) -> int:
    """Write WeChat articles to wechat_articles table."""
    create_tables()
    conn = get_db()
    saved = 0
    for url, article in cache.items():
        try:
            conn.execute(
                """INSERT OR IGNORE INTO wechat_articles
                   (url, region_id, title, account, publish_time, text, query, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    url,
                    region_id,
                    article.get("title", ""),
                    article.get("account", ""),
                    article.get("publish_time", ""),
                    article.get("text", ""),
                    article.get("query", ""),
                    article.get("fetched_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                ),
            )
            saved += 1
        except Exception as e:
            print(f"    DB save error for {url[:60]}: {e}")
    conn.commit()
    conn.close()
    print(f"  DB: {saved}/{len(cache)} records saved to wechat_articles")
    return saved


def parse_timestamps(html: str) -> list[str]:
    """Extract and convert Unix timestamps from Sogou HTML."""
    stamps = re.findall(r"timeConvert\('(\d+)'\)", html)
    return [datetime.fromtimestamp(int(s)).strftime("%Y-%m-%d") for s in stamps]


async def search_wechat(page, query: str, region_terms: list[str], exclude_terms: list[str]) -> list:
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
    region_id = DEFAULT_REGION
    for i, arg in enumerate(sys.argv):
        if arg == "--max" and i + 1 < len(sys.argv):
            max_kw = int(sys.argv[i + 1])
        elif arg == "--region" and i + 1 < len(sys.argv):
            region_id = sys.argv[i + 1]

    region = get_region(region_id)
    keywords = region["wechat_keywords"][:max_kw] if max_kw else region["wechat_keywords"]
    region_terms = region.get("wechat_region_terms", [region["name"], region["city"]])
    exclude_terms = ["招聘", "相亲", "求职", "入学", "招生", "报名", "幼儿园"]

    output_file = BASE_DIR / "data" / f"wechat_{region_id}.json"
    cache = {} if refresh else load_cache(output_file)
    new_articles = 0

    print(f"WeChat article search — {region['name']} ({region['city']})")
    print(f"  Keywords: {len(keywords)}")
    print(f"  Region terms: {region_terms}")
    print(f"  Output: {output_file}")
    print(f"  Cache: {len(cache)} existing articles\n")

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

            results = await search_wechat(page, query, region_terms, exclude_terms)
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
            save_cache(cache, output_file)

        await browser.close()

    print(f"\nDone. {new_articles} new articles, {len(cache)} total in cache")
    print(f"Saved to {output_file}")

    # Also save to DB
    if cache:
        save_wechat_to_db(cache, region_id=region_id)


if __name__ == "__main__":
    asyncio.run(main())
