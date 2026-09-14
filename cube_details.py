# DEPRECATED (2026-07-23): Use data/scrape_anjuke.py --details-only instead.
# The main scraper has richer field extraction, VL captcha solving, and crash recovery.
# This reimplementation is kept for reference only.
"""
CubeMini details-only scraper — uses synced DB, no VL/cv2 needed.
Slow rhythm, skips pages on captcha, saves back to DB.
"""
import asyncio, json, random, sys, time, re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.async_api import async_playwright
from config import USER_AGENT

sys.stdout.reconfigure(line_buffering=True)
from db.connection import get_db
from db.schema import create_tables
from data.scrapers.stealth import STEALTH_JS

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "anjuke_state.json"

DELAY_MIN = 8   # seconds between detail pages
DELAY_MAX = 20


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def _has_captcha(page):
    try:
        return "验证" in (await page.title())
    except Exception:
        return True


def load_from_db(region_id):
    conn = get_db()
    rows = conn.execute(
        """SELECT community_id, name FROM communities
           WHERE region_id = ? AND detail_scraped_at IS NULL""",
        (region_id,)
    ).fetchall()
    conn.close()
    communities = []
    for row in rows:
        cid = row["community_id"]
        name = row["name"]
        parts = cid.split("_")
        anjuke_id = parts[-1] if parts[-1].isdigit() else ""
        city_slug = region_id.split("_")[0]
        url = f"https://{city_slug}.anjuke.com/community/view/{anjuke_id}" if anjuke_id.isdigit() else ""
        communities.append({
            "name": name, "url": url, "community_id": cid,
            "community_id_anjuke": anjuke_id, "city_slug": city_slug,
        })
    return communities


async def scrape_detail(page, c):
    url = c.get("url", "")
    if not url:
        return c
    print(f"  [{now_str()}] {c['name']}")

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            return c
    await asyncio.sleep(2)

    if await _has_captcha(page):
        print(f"    Captcha — waiting 30s...")
        for _ in range(15):
            await asyncio.sleep(2)
            try:
                if not await _has_captcha(page):
                    print(f"    Cleared!")
                    break
            except Exception:
                pass
        else:
            print(f"    Skipping (captcha timeout)")
            return c

    result = dict(c)
    full_text = await page.evaluate("() => document.body?.innerText || ''")

    # Coordinates
    loc = await page.evaluate("""() => {
        const m = document.querySelector('meta[name="location"]');
        return m ? m.getAttribute('content') || '' : '';
    }""")
    coord_m = re.search(r"coord=([\d.]+),([\d.]+)", loc)
    if coord_m:
        result["coordinate_lng"] = float(coord_m.group(1))
        result["coordinate_lat"] = float(coord_m.group(2))

    # Basic fields
    for key, pat in [
        ("year_built", r"竣工时间\s*(\d{4})"),
        ("total_units", r"总户数\s*(\d+)"),
        ("floor_area_ratio", r"容积率\s*([\d.]+)"),
        ("green_ratio", r"绿化率\s*([\d.]+)"),
        ("property_fee", r"物业费\s*([\d.]+)"),
    ]:
        m = re.search(pat, full_text)
        if not m:
            continue
        val = m.group(1).strip()
        if key in ("year_built", "total_units"):
            d = re.search(r"(\d+)", val)
            if d:
                result[key] = int(d.group(1))
        elif key in ("floor_area_ratio", "green_ratio", "property_fee"):
            d = re.search(r"(\d+\.?\d*)", val)
            if d:
                try:
                    result[key] = float(d.group(1))
                except ValueError:
                    pass

    # Label-value pairs
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

    # Price
    if not result.get("avg_price"):
        price_m = re.search(r"(\d{3,6})\s*元/[平㎡]", full_text)
        if price_m:
            result["avg_price"] = int(price_m.group(1))

    # Sale/Rent counts
    sale_m = re.search(r"在售房源[：:]?\s*(\d+)\s*套", full_text)
    if sale_m:
        result["on_sale_count"] = int(sale_m.group(1))
    rent_m = re.search(r"在租房源[：:]?\s*(\d+)\s*套", full_text)
    if rent_m:
        result["on_rent_count"] = int(rent_m.group(1))

    result["data_updated"] = now_str()
    if any(result.get(k) for k in ["year_built", "developer", "property_mgmt", "coordinate_lng"]):
        result["detail_scraped_at"] = now_str()

    fields = sum(1 for k in ["year_built","developer","property_mgmt","coordinate_lng","avg_price","on_sale_count"] if result.get(k))
    print(f"    {fields}/6 fields" + (f" ({result['coordinate_lng']:.4f},{result['coordinate_lat']:.4f})" if result.get("coordinate_lng") else ""))
    return result


def save_to_db(communities, region_id):
    create_tables()
    conn = get_db()
    saved = 0
    for c in communities:
        cid = c.get("community_id", "")
        try:
            conn.execute(
                """INSERT OR REPLACE INTO communities
                   (community_id, name, address, year_built, developer,
                    property_mgmt, property_fee, floor_area_ratio, green_ratio,
                    total_units, avg_price, listing_count,
                    coordinate_lng, coordinate_lat, on_sale_count, on_rent_count,
                    data_source, data_updated, region_id, detail_scraped_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, c.get("name"), c.get("address"), c.get("year_built"),
                 c.get("developer"), c.get("property_mgmt"), c.get("property_fee"),
                 c.get("floor_area_ratio"), c.get("green_ratio"),
                 c.get("total_units"), c.get("avg_price"), c.get("listing_count"),
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


async def main():
    region_id = sys.argv[1] if len(sys.argv) > 1 else "beijing_chaoyang"
    create_tables()

    communities = load_from_db(region_id)
    print(f"[{now_str()}] Cube details scraper")
    print(f"  Region: {region_id}")
    print(f"  Queued: {len(communities)} communities")
    print(f"  Rhythm: {DELAY_MIN}-{DELAY_MAX}s per page")
    print("=" * 50)

    if not communities:
        print("  Nothing to do!")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path='/usr/bin/chromium-browser',
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                  "--disable-gpu", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        saved_count = 0
        for i, c in enumerate(communities):
            try:
                communities[i] = await scrape_detail(page, c)
            except Exception as e:
                print(f"    Error: {e}")

            if (i > 0 and i % 10 == 0) or i == len(communities) - 1:
                end = i + 1
                save_to_db(communities[:end], region_id)
                saved_count = end
                print(f"  [saved {saved_count}/{len(communities)}]")

            if i < len(communities) - 1:
                delay = random.randint(DELAY_MIN, DELAY_MAX)
                await asyncio.sleep(delay)

        # Save session
        try:
            state = await context.storage_state()
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception:
            pass
        await browser.close()

    print(f"\n[{now_str()}] Done: {saved_count}/{len(communities)} saved")


if __name__ == "__main__":
    asyncio.run(main())
