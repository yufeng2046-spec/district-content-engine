"""
Anjuke community scraper for Yangling district.
Uses stealth JS + cookie persistence to handle anti-bot captcha.

First run: python data/scrape_anjuke.py --login    (visible browser, solve captcha)
Then:      python data/scrape_anjuke.py --max 5    (headless with saved cookies)
Debug:     python data/scrape_anjuke.py --max 3 --show

Usage:
    PYTHONPATH=. python3 data/scrape_anjuke.py --login
    PYTHONPATH=. python3 data/scrape_anjuke.py --max 5
    PYTHONPATH=. python3 data/scrape_anjuke.py --max 3 --show
"""

import asyncio
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    ANJUKE_YANGLING_URL, USER_AGENT,
    REGION_ID, REGION_NAME,
    PAGE_DELAY_MIN_MS, PAGE_DELAY_MAX_MS,
    DETAIL_DELAY_MIN_MS, DETAIL_DELAY_MAX_MS,
)
from db.connection import get_db
from db.schema import create_tables

BASE_DIR = Path(__file__).resolve().parent.parent
COOKIES_FILE = BASE_DIR / "anjuke_cookies.json"

STEALTH_JS = r"""
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
const _origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : _origQuery(parameters)
);
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' },
        ];
        arr.item = (i) => arr[i]; arr.namedItem = (n) => arr.find(p => p.name === n);
        arr.refresh = () => {};
        Object.setPrototypeOf(arr, PluginArray.prototype);
        return arr;
    }
});
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
"""


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.strip().lower().replace(" ", "_"))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_cookies() -> list[dict]:
    if COOKIES_FILE.exists():
        with open(COOKIES_FILE) as f:
            return json.load(f)
    return []


def save_cookies(cookies: list[dict]) -> None:
    with open(COOKIES_FILE, "w") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    print(f"  Cookies saved to {COOKIES_FILE}")


async def login_and_save_cookies() -> bool:
    """Open visible browser, let user solve captcha, save cookies."""
    print("Opening Anjuke for manual verification (visible browser)...")
    print("Please solve the captcha, then press Enter here.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        await page.goto(ANJUKE_YANGLING_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)
        title = await page.title()
        print(f"  Title: {title}")

        if "验证" in title or "captcha" in title.lower():
            print("  Captcha detected — solve it in the browser, then press Enter.")
            input("  Press Enter when ready...")
            title = await page.title()
            print(f"  Title after: {title}")

        cookies = await context.cookies()
        save_cookies(cookies)
        # Also save full storage state (localStorage, sessionStorage, etc.)
        state_file = BASE_DIR / "anjuke_state.json"
        await context.storage_state(path=str(state_file))
        print(f"  Storage state saved to {state_file}")
        await browser.close()
        return True


async def scrape_listing_page(page, url: str) -> list[dict]:
    """Scrape a single listing page, return parsed communities."""
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(2000)

    title = await page.title()
    if "验证" in title:
        print("  Still hitting captcha. Run --login in visible mode first.")
        return []

    raw_links = await page.evaluate("""() => {
        const links = [];
        document.querySelectorAll('a[href*="/community/view/"]').forEach(a => {
            const href = a.getAttribute('href');
            if (href && /\/community\/view\/\\d+$/.test(href)) {
                links.push({url: a.href, text: a.textContent.trim()});
            }
        });
        return links;
    }""")

    communities = []
    seen_ids = set()

    for link in raw_links:
        cid_m = re.search(r"/community/view/(\d+)", link["url"])
        if not cid_m:
            continue
        cid = cid_m.group(1)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        text = link["text"]

        name = ""
        name_m = re.match(r"^(\S+)", text)
        if name_m:
            name = name_m.group(1)

        year_m = re.search(r"(\d{4})年[竣建]", text)
        year_built = int(year_m.group(1)) if year_m else None

        addr = ""
        addr_m = re.search(r"年[竣建](.*?)二手房", text)
        if addr_m:
            addr = addr_m.group(1).strip()

        price = None
        price_m = re.search(r"(\d{3,6})\s*元/m", text)
        if price_m:
            price = int(price_m.group(1))

        listing_count = None
        listing_m = re.search(r"二手房\((\d+)\)", text)
        if listing_m:
            listing_count = int(listing_m.group(1))

        communities.append({
            "name": name,
            "url": link["url"],
            "community_id_anjuke": cid,
            "avg_price": price,
            "listing_count": listing_count,
            "year_built": year_built,
            "address": addr,
        })

    return communities


async def scrape_listing(page, max_communities: int = 0) -> list[dict]:
    """Scrape all listing pages. max_communities=0 means unlimited."""
    all_communities = []
    seen_ids = set()

    for pg in range(1, 30):  # safety cap at 30 pages
        url = ANJUKE_YANGLING_URL if pg == 1 else f"{ANJUKE_YANGLING_URL}p{pg}/"
        print(f"\n  Page {pg}: {url}")

        page_communities = await scrape_listing_page(page, url)
        if not page_communities:
            print(f"  Page {pg}: empty or captcha, stopping pagination")
            break

        new_count = 0
        for c in page_communities:
            cid = c["community_id_anjuke"]
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_communities.append(c)
                new_count += 1

        print(f"  Page {pg}: {new_count} new communities (running total: {len(all_communities)})")

        if max_communities > 0 and len(all_communities) >= max_communities:
            all_communities = all_communities[:max_communities]
            print(f"  Reached max_communities={max_communities}, stopping")
            break

        # Small delay between pages
        await page.wait_for_timeout(random.randint(2000, 4000))

    return all_communities


async def scrape_detail(page, community: dict) -> dict:
    """Scrape community detail page — parse dense property info text."""
    url = community.get("url", "")
    if not url:
        return community

    print(f"    Loading: {community['name']}")
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"    Nav error: {e}")
        return community

    if "验证" in await page.title():
        print(f"    Captcha on detail page, skipping")
        return community

    result = dict(community)

    # (A) JS extraction: label/value pairs (developer, property_mgmt, address)
    # and location meta tag (coordinates)
    js_info = await page.evaluate("""() => {
        const data = {};
        document.querySelectorAll('.label').forEach(label => {
            const key = label.textContent.trim();
            const valueEl = label.nextElementSibling;
            if (valueEl && valueEl.classList.contains('value')) {
                const val = valueEl.textContent.trim();
                if (key && val && key.length < 20 && val.length < 200) {
                    data[key] = val;
                }
            }
        });
        const locMeta = document.querySelector('meta[name="location"]');
        if (locMeta) data._location = locMeta.getAttribute('content');
        return data;
    }""")

    label_map = {
        "开发商": "developer", "物业公司": "property_mgmt",
        "小区地址": "address", "停车费": "parking_fee",
    }
    for cn_key, en_key in label_map.items():
        if cn_key in js_info:
            result[en_key] = js_info[cn_key]

    # Coordinates from <meta name="location" content="...coord=lng,lat">
    coord_found = False
    loc = js_info.get("_location", "")
    coord_m = re.search(r"coord=([\d.]+),([\d.]+)", loc)
    if coord_m:
        result["coordinate_lng"] = float(coord_m.group(1))
        result["coordinate_lat"] = float(coord_m.group(2))
        coord_found = True

    # (B) Text parsing: dense property info line
    # "竣工时间 2011年...总户数 1559户...容积率 2.00绿化率 30.0%...停车位 220(1:0.1)物业费 0.50"
    full_text = await page.evaluate("() => document.body.innerText")

    dense_matches = {
        "year_built": r"竣工时间\s*(\d{4})",
        "total_units": r"总户数\s*(\d+)",
        "floor_area_ratio": r"容积率\s*([\d.]+)",
        "green_ratio": r"绿化率\s*([\d.]+)",
        "property_fee": r"物业费\s*([\d.]+)",
        "building_types": r"建筑类型\s*(.+?)(?:所属商圈|统一供暖|供水|$)",
        "parking_ratio": r"停车位\s*(\d+.*?)(?:物业费|统一供暖|供水|$)",
    }

    for key, pat in dense_matches.items():
        m = re.search(pat, full_text)
        if not m:
            continue
        val = m.group(1).strip().rstrip("。")
        if key in ("year_built", "total_units"):
            digits = re.search(r"(\d+)", val)
            if digits:
                result[key] = int(digits.group(1))
        elif key in ("floor_area_ratio", "green_ratio", "property_fee"):
            digits = re.search(r"(\d+\.?\d*)", val)
            if digits:
                try:
                    result[key] = float(digits.group(1))
                except (ValueError, AttributeError):
                    pass
        elif key == "building_types":
            # Clean up: only keep building type keywords
            types = re.findall(r"(?:多层|小高层?|高层|塔楼|板楼|别墅|联排|独栋|洋房)", val)
            if types:
                result[key] = json.dumps(types, ensure_ascii=False)
        else:
            result[key] = val

    # Features / selling points
    features_m = re.search(r"【小区[优点特]】(.+?)(?:【|$)", full_text)
    if features_m:
        result["features"] = json.dumps(
            [f.strip() for f in features_m.group(1).split("，") if f.strip()],
            ensure_ascii=False,
        )

    # Price fallback
    if not result.get("avg_price"):
        price_m = re.search(r"(\d{3,6})\s*元/[平㎡]", full_text)
        if price_m:
            result["avg_price"] = int(price_m.group(1))

    fields_got = sum(1 for k in ["year_built", "developer", "property_mgmt", "property_fee",
                                   "floor_area_ratio", "green_ratio", "parking_ratio",
                                   "total_units", "building_types", "avg_price"] if result.get(k))
    print(f"    Fields: {fields_got}/10" + (f"  Coord: {result.get('coordinate_lng')}, {result.get('coordinate_lat')}" if coord_found else "  No coords"))

    return result


def save_to_db(communities: list[dict]) -> int:
    create_tables()
    conn = get_db()
    saved = 0
    for c in communities:
        # Use Anjuke numeric ID to avoid Chinese-character slug collisions
        anjuke_id = c.get("community_id_anjuke", "")
        cid = f"{REGION_ID}_{anjuke_id}" if anjuke_id else f"{REGION_ID}_{slugify(c.get('name',''))}"
        try:
            conn.execute(
                """INSERT OR REPLACE INTO communities
                   (community_id, name, address, year_built, developer,
                    property_mgmt, property_fee, floor_area_ratio, green_ratio,
                    parking_ratio, total_units, building_types, unit_sizes,
                    avg_price, listing_count, features,
                    coordinate_lng, coordinate_lat, data_source, data_updated)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, c.get("name"), c.get("address"), c.get("year_built"),
                 c.get("developer"), c.get("property_mgmt"), c.get("property_fee"),
                 c.get("floor_area_ratio"), c.get("green_ratio"), c.get("parking_ratio"),
                 c.get("total_units"), c.get("building_types"), c.get("unit_sizes"),
                 c.get("avg_price"), c.get("listing_count"), c.get("features"),
                 c.get("coordinate_lng"), c.get("coordinate_lat"),
                 "anjuke", now_str()),
            )
            saved += 1
        except Exception as e:
            print(f"    DB save error {c.get('name')}: {e}")
    conn.commit()
    conn.close()
    print(f"  Saved {saved}/{len(communities)}")
    return saved


async def main():
    create_tables()
    max_communities = 0  # 0 = unlimited, scrape all pages
    show_browser = False
    login_mode = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--max" and i + 1 < len(args):
            max_communities = int(args[i + 1]); i += 2
        elif args[i] == "--show":
            show_browser = True; i += 1
        elif args[i] == "--login":
            login_mode = True; i += 1
        else:
            i += 1

    if login_mode:
        await login_and_save_cookies()
        return

    cookies = load_cookies()
    if not cookies:
        print("No cookies. Run --login first to solve captcha.")
        return

    print(f"Anjuke Scraper — {REGION_NAME}  (max: {max_communities or 'all'})")
    print(f"  Cookies: {len(cookies)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not show_browser,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
        )
        await context.add_cookies(cookies)
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        print("\n[1/2] Scraping listing...")
        communities = await scrape_listing(page, max_communities)
        print(f"  Found {len(communities)} communities")

        if not communities:
            await browser.close()
            return

        print("\n[2/2] Scraping detail pages...")
        for i, c in enumerate(communities):
            print(f"\n  [{i+1}/{len(communities)}] {c['name']}")
            communities[i] = await scrape_detail(page, c)
            delay_s = random.uniform(DETAIL_DELAY_MIN_MS, DETAIL_DELAY_MAX_MS) / 1000
            print(f"    Waiting {delay_s:.0f}s...")
            await page.wait_for_timeout(int(delay_s * 1000))

        save_cookies(await context.cookies())
        await browser.close()

    print(f"\nSaving to DB...")
    saved = save_to_db(communities)
    print(f"Done. {saved}/{len(communities)} saved.")


if __name__ == "__main__":
    asyncio.run(main())
