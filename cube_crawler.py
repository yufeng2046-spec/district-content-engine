# DEPRECATED (2026-07-23): Use data/scrape_anjuke.py --shangquan all instead.
# The main scraper supersedes this with VL captcha solving, richer enrichment,
# progress tracking, and per-city state files. Kept for reference only.
"""
CubeMini unattended crawler — slow, steady, human-like rhythm.
Uses system Chromium with persistent profile to build session reputation.

Usage:
    ssh cubemini
    cd ~/district-content-engine
    ~/crawler-venv/bin/python cube_crawler.py

First run: solve one captcha manually, then it runs unattended.
"""

import asyncio, json, random, sys, time, re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.async_api import async_playwright
from config import USER_AGENT, PAGE_DELAY_MIN_MS, PAGE_DELAY_MAX_MS

# Force unbuffered output for real-time log monitoring
sys.stdout.reconfigure(line_buffering=True)
from db.connection import get_db
from db.schema import create_tables
from data.scrapers.stealth import STEALTH_JS

BASE_DIR = Path(__file__).resolve().parent
CHROME_PROFILE = BASE_DIR / "chrome_profile_cube"
STATE_FILE = CHROME_PROFILE / "state.json"
PROGRESS_FILE = BASE_DIR / "cube_progress.json"

# ── Slow rhythm: mimic a real person browsing ──
LISTING_PAUSE_MIN = 25   # seconds between listing pages
LISTING_PAUSE_MAX = 45
DETAIL_PAUSE_MIN = 35    # seconds between detail pages
DETAIL_PAUSE_MAX = 65
SHANGQUAN_COOLDOWN = 120  # seconds between shangquan batches
CAPTCHA_RETRY_DELAY = 30  # seconds before retry after captcha

# ── City queue: regions CubeMini is responsible for ──
# Format: (region_id, city_slug, district_name, shangquan_json_file)
# These are populated progressively.
CITY_QUEUE: list[dict] = []


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"completed": [], "current": None, "total_scraped": 0}


def save_progress(progress: dict) -> None:
    PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2))


async def wait_human(seconds: int | None = None, jitter: int = 10) -> None:
    """Wait like a human — variable duration."""
    if seconds is None:
        seconds = random.randint(30, 60)
    actual = seconds + random.randint(-jitter, jitter)
    actual = max(5, actual)
    await asyncio.sleep(actual)


async def _has_captcha(page) -> bool:
    try:
        title = await page.title()
        return "验证" in title
    except Exception:
        return True


async def wait_for_captcha_clear(page, timeout_seconds: int = 120) -> bool:
    """Poll until captcha is cleared by user or timeout."""
    for _ in range(timeout_seconds // 3):
        await asyncio.sleep(3)
        try:
            if not await _has_captcha(page):
                return True
        except Exception:
            pass
    return False


async def scrape_listing_slow(page, url: str, max_pages: int = 5) -> list[dict]:
    """Slow listing scraper — pauses between pages like a real user."""
    all_communities = []
    seen_ids = set()

    for pg in range(1, max_pages + 1):
        page_url = url if pg == 1 else f"{url.rstrip('/')}/p{pg}/"
        print(f"    [{now_str()}] Listing p{pg}: {page_url}")

        try:
            await page.goto(page_url, wait_until="networkidle", timeout=30000)
        except Exception:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

        # Random scroll
        await page.evaluate("window.scrollBy(0, 200 + Math.random() * 400)")
        await asyncio.sleep(random.uniform(2, 5))

        # Captcha check
        if await _has_captcha(page):
            print(f"    [!] Captcha on listing page — waiting for manual solve...")
            cleared = await wait_for_captcha_clear(page)
            if not cleared:
                print(f"    Captcha timeout, skipping page")
                continue
            print(f"    Captcha cleared, reloading...")
            try:
                await page.goto(page_url, wait_until="networkidle", timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(3)

        title = await page.title()
        if "验证" in title:
            print(f"    Captcha persists, skipping page")
            continue

        # Extract communities
        raw_links = await page.evaluate("""() => {
            const links = [];
            document.querySelectorAll('a[href*="/community/view/"]').forEach(a => {
                const href = a.getAttribute('href');
                if (href && /\\/community\\/view\\/\\d+$/.test(href)) {
                    links.push({url: a.href, text: a.textContent.trim()});
                }
            });
            return links;
        }""")

        new_count = 0
        for link in raw_links:
            cid_m = re.search(r"/community/view/(\d+)", link["url"])
            if not cid_m:
                continue
            cid = cid_m.group(1)
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            text = link["text"]
            name_m = re.match(r"^(\S+)", text)
            name = name_m.group(1) if name_m else ""
            price_m = re.search(r"(\d{3,6})\s*元/m", text)
            price = int(price_m.group(1)) if price_m else None
            year_m = re.search(r"(\d{4})年", text)
            year = int(year_m.group(1)) if year_m else None
            listing_m = re.search(r"二手房\((\d+)\)", text)
            listing_count = int(listing_m.group(1)) if listing_m else None

            all_communities.append({
                "name": name,
                "url": link["url"],
                "community_id_anjuke": cid,
                "avg_price": price,
                "listing_count": listing_count,
                "year_built": year,
            })
            new_count += 1

        print(f"    p{pg}: {new_count} new (total: {len(all_communities)})")

        if new_count == 0 and pg > 1:
            print(f"    Empty page, stopping pagination")
            break

        # Human-like pause between pages
        if pg < max_pages:
            pause = random.randint(LISTING_PAUSE_MIN, LISTING_PAUSE_MAX)
            print(f"    Pausing {pause}s...")
            await asyncio.sleep(pause)

    return all_communities


async def scrape_detail_slow(page, community: dict) -> dict:
    """Slow detail scraper with human-like pauses."""
    url = community.get("url", "")
    if not url:
        return community

    name = community.get("name", "?")
    print(f"    [{now_str()}] Detail: {name}")

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            return community

    await asyncio.sleep(2)

    # Random scroll behavior
    await page.evaluate("window.scrollBy(0, 300 + Math.random() * 600)")
    await asyncio.sleep(random.uniform(1, 3))
    await page.evaluate("window.scrollBy(0, 300 + Math.random() * 400)")
    await asyncio.sleep(random.uniform(1, 2))

    # Captcha check
    if await _has_captcha(page):
        print(f"    [!] Captcha on detail page — waiting...")
        cleared = await wait_for_captcha_clear(page)
        if not cleared:
            return community
        await asyncio.sleep(2)

    result = dict(community)
    full_text = await page.evaluate("() => document.body?.innerText || ''")

    # ── Coordinates ──
    loc = await page.evaluate("""() => {
        const m = document.querySelector('meta[name="location"]');
        return m ? m.getAttribute('content') || '' : '';
    }""")
    coord_m = re.search(r"coord=([\d.]+),([\d.]+)", loc)
    if coord_m:
        result["coordinate_lng"] = float(coord_m.group(1))
        result["coordinate_lat"] = float(coord_m.group(2))

    # ── Basic fields ──
    dense_matches = {
        "year_built": r"竣工时间\s*(\d{4})",
        "total_units": r"总户数\s*(\d+)",
        "floor_area_ratio": r"容积率\s*([\d.]+)",
        "green_ratio": r"绿化率\s*([\d.]+)",
        "property_fee": r"物业费\s*([\d.]+)",
        "building_types": r"建筑类型\s*(.+?)(?:所属商圈|统一供暖|供水|$)",
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
            types = re.findall(r"(?:多层|小高层?|高层|塔楼|板楼|别墅|联排|独栋|洋房)", val)
            if types:
                result[key] = json.dumps(types, ensure_ascii=False)
        else:
            result[key] = val

    # ── Label-value pairs ──
    label_map = {"开发商": "developer", "物业公司": "property_mgmt", "小区地址": "address"}
    js_info = await page.evaluate("""() => {
        const data = {};
        document.querySelectorAll('.label').forEach(label => {
            const key = label.textContent.trim();
            const valueEl = label.nextElementSibling;
            if (valueEl) {
                const val = valueEl.textContent.trim();
                if (key && val && key.length < 20 && val.length < 200) data[key] = val;
            }
        });
        return data;
    }""")
    for cn_key, en_key in label_map.items():
        if cn_key in js_info:
            result[en_key] = js_info[cn_key]

    # ── Price ──
    if not result.get("avg_price"):
        price_m = re.search(r"(\d{3,6})\s*元/[平㎡]", full_text)
        if price_m:
            result["avg_price"] = int(price_m.group(1))

    # ── Sale/Rent counts ──
    sale_m = re.search(r"在售房源[：:]?\s*(\d+)\s*套", full_text)
    if sale_m:
        result["on_sale_count"] = int(sale_m.group(1))
    rent_m = re.search(r"在租房源[：:]?\s*(\d+)\s*套", full_text)
    if rent_m:
        result["on_rent_count"] = int(rent_m.group(1))

    result["data_updated"] = now_str()
    if any(result.get(k) for k in ["year_built", "developer", "property_mgmt", "coordinate_lng"]):
        result["detail_scraped_at"] = now_str()

    fields = sum(1 for k in ["year_built","developer","property_mgmt","coordinate_lng",
                              "avg_price","on_sale_count","floor_area_ratio","green_ratio"] if result.get(k))
    coord = ""
    if result.get("coordinate_lng"):
        coord = f" coord({result['coordinate_lng']:.4f},{result['coordinate_lat']:.4f})"
    print(f"    {fields}/8 fields{coord}")

    return result


def save_to_db(communities: list[dict], region_id: str) -> int:
    """Save communities to local SQLite."""
    create_tables()
    conn = get_db()
    saved = 0
    for c in communities:
        cid = c.get("community_id", "")
        if not cid:
            anjuke_id = c.get("community_id_anjuke", "")
            name = c.get("name", "")
            cid = f"{region_id}_{anjuke_id}" if anjuke_id else f"{region_id}_{name}"
        try:
            conn.execute(
                """INSERT OR REPLACE INTO communities
                   (community_id, name, address, year_built, developer,
                    property_mgmt, property_fee, floor_area_ratio, green_ratio,
                    total_units, building_types, avg_price, listing_count,
                    coordinate_lng, coordinate_lat, on_sale_count, on_rent_count,
                    data_source, data_updated, region_id, detail_scraped_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, c.get("name"), c.get("address"), c.get("year_built"),
                 c.get("developer"), c.get("property_mgmt"), c.get("property_fee"),
                 c.get("floor_area_ratio"), c.get("green_ratio"),
                 c.get("total_units"), c.get("building_types"),
                 c.get("avg_price"), c.get("listing_count"),
                 c.get("coordinate_lng"), c.get("coordinate_lat"),
                 c.get("on_sale_count"), c.get("on_rent_count"),
                 "anjuke", now_str(), region_id, c.get("detail_scraped_at")),
            )
            saved += 1
        except Exception as e:
            print(f"    DB save error {c.get('name')}: {e}")
    conn.commit()
    conn.close()
    return saved


async def run_city(page, region_id: str, city_slug: str,
                   district_name: str, anjuke_url: str) -> dict:
    """Run a full city scrape: listing + details, slow rhythm."""
    print(f"\n{'='*60}")
    print(f"[{now_str()}] City: {district_name} ({region_id})")
    print(f"  URL: {anjuke_url}")
    print(f"{'='*60}")

    # Phase 1: Scrape listing
    print(f"\n  [Phase 1] Listing scrape...")
    communities = await scrape_listing_slow(page, anjuke_url)
    print(f"  Found {len(communities)} communities")

    if not communities:
        return {"region_id": region_id, "scraped": 0, "saved": 0}

    # Phase 2: Detail pages
    print(f"\n  [Phase 2] Detail scrape ({len(communities)} pages)...")
    saved_count = 0
    for i, c in enumerate(communities):
        try:
            communities[i] = await scrape_detail_slow(page, c)
        except Exception as e:
            print(f"    Error: {e}")

        # Incremental save every 5
        if (i > 0 and i % 5 == 0) or i == len(communities) - 1:
            save_to_db(communities[:i + 1], region_id)
            saved_count = i + 1
            print(f"    [saved {saved_count}/{len(communities)}]")

        # Human-like pause
        if i < len(communities) - 1:
            pause = random.randint(DETAIL_PAUSE_MIN, DETAIL_PAUSE_MAX)
            await asyncio.sleep(pause)

    # Final save
    saved = save_to_db(communities, region_id)
    print(f"\n  Done: {region_id} — {saved}/{len(communities)} saved")
    return {"region_id": region_id, "scraped": len(communities), "saved": saved}


async def main():
    create_tables()
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)

    # ── City queue ──
    # Start with Zhangjiakou itself (local IP, most natural)
    cities = [
        # (region_id, city_slug, district_name, anjuke_listing_url)
        ("zhangjiakou_qiaodong", "zhangjiakou", "桥东", "https://zhangjiakou.anjuke.com/community/qiaodong/"),
        ("zhangjiakou_qiaoxi", "zhangjiakou", "桥西", "https://zhangjiakou.anjuke.com/community/qiaoxi/"),
        # Add more cities as we expand
    ]

    print("=" * 60)
    print(f"[{now_str()}] CubeMini Unattended Crawler")
    print(f"  Profile: {CHROME_PROFILE}")
    print(f"  Queue: {len(cities)} cities")
    print(f"  Rhythm: {LISTING_PAUSE_MIN}-{LISTING_PAUSE_MAX}s listing, {DETAIL_PAUSE_MIN}-{DETAIL_PAUSE_MAX}s detail")
    print("=" * 60)

    async with async_playwright() as p:
        # Use regular launch + new_context with storage_state
        # (persistent_context doesn't support storage_state properly)
        browser = await p.chromium.launch(
            executable_path='/usr/bin/chromium-browser',
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--disable-gpu", "--disable-dev-shm-usage"],
        )

        storage_state = str(STATE_FILE) if STATE_FILE.exists() else None
        if storage_state:
            print(f"  Loading session state...")

        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            storage_state=storage_state,
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        progress = load_progress()
        print(f"  Previous progress: {progress.get('total_scraped', 0)} total, {len(progress.get('completed', []))} cities done")

        for city in cities:
            rid = city[0]
            if rid in progress.get("completed", []):
                print(f"\n  [{rid}] Already completed, skipping")
                continue

            result = await run_city(page, *city)
            progress["total_scraped"] = progress.get("total_scraped", 0) + result["scraped"]
            if result["saved"] > 0:
                progress["completed"].append(rid)
            save_progress(progress)

            # Cooldown between cities
            cooldown = random.randint(300, 600)  # 5-10 min
            print(f"\n  City cooldown: {cooldown // 60} min...")
            await asyncio.sleep(cooldown)

        # Save updated session state
        try:
            state = await context.storage_state()
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
            print(f"  Session saved: {len(state.get('cookies',[]))} cookies")
        except Exception as e:
            print(f"  State save warning: {e}")
        await browser.close()

    print(f"\n{'='*60}")
    print(f"[{now_str()}] Crawl session complete")
    print(f"  Total scraped: {progress['total_scraped']}")
    print(f"  Cities: {progress['completed']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
