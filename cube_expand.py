# DEPRECATED (2026-07-23): Use data/scrape_anjuke.py --shangquan all instead.
# The main scraper has VL captcha solving, richer enrichment, progress tracking,
# and per-city state files. This reimplementation is kept for reference only.
"""
CubeMini city-expansion crawler — covers new cities with slow human-like rhythm.
Each city: scrape listing pages → scrape detail pages → save to DB.
Residential Zhangjiakou IP minimizes captcha risk.
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
PROGRESS_FILE = BASE_DIR / "cube_expand_progress.json"

LISTING_PAUSE = (15, 30)   # seconds between listing pages
DETAIL_PAUSE = (8, 18)     # seconds between detail pages
CITY_COOLDOWN = (120, 300) # seconds between cities

# ── City expansion queue ──
# (region_id, city_name, anjuke_community_url)
# All Tier-1 and Tier-2 cities not yet covered
NEW_CITIES = [
    # ═══ Tier 1 ═══
    ("shanghai", "上海", "https://shanghai.anjuke.com/community/"),
    ("guangzhou", "广州", "https://guangzhou.anjuke.com/community/"),
    ("shenzhen", "深圳", "https://shenzhen.anjuke.com/community/"),
    # ═══ New Tier 1 ═══
    ("hangzhou", "杭州", "https://hangzhou.anjuke.com/community/"),
    ("wuhan", "武汉", "https://wuhan.anjuke.com/community/"),
    ("nanjing", "南京", "https://nanjing.anjuke.com/community/"),
    ("tianjin", "天津", "https://tianjin.anjuke.com/community/"),
    ("suzhou", "苏州", "https://suzhou.anjuke.com/community/"),
    ("chongqing", "重庆", "https://chongqing.anjuke.com/community/"),
    ("changsha", "长沙", "https://changsha.anjuke.com/community/"),
    ("zhengzhou", "郑州", "https://zhengzhou.anjuke.com/community/"),
    ("dongguan", "东莞", "https://dongguan.anjuke.com/community/"),
    ("qingdao", "青岛", "https://qingdao.anjuke.com/community/"),
    ("shenyang", "沈阳", "https://shenyang.anjuke.com/community/"),
    ("ningbo", "宁波", "https://ningbo.anjuke.com/community/"),
    ("kunming", "昆明", "https://kunming.anjuke.com/community/"),
    # ═══ Tier 2 ═══
    ("wuxi", "无锡", "https://wuxi.anjuke.com/community/"),
    ("foshan", "佛山", "https://foshan.anjuke.com/community/"),
    ("hefei", "合肥", "https://hefei.anjuke.com/community/"),
    ("dalian", "大连", "https://dalian.anjuke.com/community/"),
    ("fuzhou", "福州", "https://fuzhou.anjuke.com/community/"),
    ("xiamen", "厦门", "https://xiamen.anjuke.com/community/"),
    ("haerbin", "哈尔滨", "https://haerbin.anjuke.com/community/"),
    ("jinan", "济南", "https://jinan.anjuke.com/community/"),
    ("wenzhou", "温州", "https://wenzhou.anjuke.com/community/"),
    ("nanning", "南宁", "https://nanning.anjuke.com/community/"),
    ("changchun", "长春", "https://changchun.anjuke.com/community/"),
    ("shijiazhuang", "石家庄", "https://shijiazhuang.anjuke.com/community/"),
    ("guiyang", "贵阳", "https://guiyang.anjuke.com/community/"),
    ("nanchang", "南昌", "https://nanchang.anjuke.com/community/"),
    ("jiaxing", "嘉兴", "https://jiaxing.anjuke.com/community/"),
    ("taiyuan", "太原", "https://taiyuan.anjuke.com/community/"),
    ("xuzhou", "徐州", "https://xuzhou.anjuke.com/community/"),
    ("huizhou", "惠州", "https://huizhou.anjuke.com/community/"),
    ("zhuhai", "珠海", "https://zhuhai.anjuke.com/community/"),
    ("zhongshan", "中山", "https://zhongshan.anjuke.com/community/"),
    ("yantai", "烟台", "https://yantai.anjuke.com/community/"),
    ("lanzhou", "兰州", "https://lanzhou.anjuke.com/community/"),
    ("haikou", "海口", "https://haikou.anjuke.com/community/"),
    ("yangzhou", "扬州", "https://yangzhou.anjuke.com/community/"),
    # ═══ Tier 3 ═══
    ("luoyang", "洛阳", "https://luoyang.anjuke.com/community/"),
    ("weihai", "威海", "https://weihai.anjuke.com/community/"),
    ("huzhou", "湖州", "https://huzhou.anjuke.com/community/"),
    ("zibo", "淄博", "https://zibo.anjuke.com/community/"),
    ("baoding", "保定", "https://baoding.anjuke.com/community/"),
    ("quanzhou", "泉州", "https://quanzhou.anjuke.com/community/"),
    ("weifang", "潍坊", "https://weifang.anjuke.com/community/"),
    ("jinhua", "金华", "https://jinhua.anjuke.com/community/"),
    ("nantong", "南通", "https://nantong.anjuke.com/community/"),
    ("shaoxing", "绍兴", "https://shaoxing.anjuke.com/community/"),
    ("changzhou", "常州", "https://changzhou.anjuke.com/community/"),
    ("taizhou_js", "台州", "https://taizhou.anjuke.com/community/"),
    ("liuzhou", "柳州", "https://liuzhou.anjuke.com/community/"),
    ("guiLin", "桂林", "https://guilin.anjuke.com/community/"),
    ("beihai", "北海", "https://beihai.anjuke.com/community/"),
    ("sanya", "三亚", "https://sanya.anjuke.com/community/"),
    ("yichang", "宜昌", "https://yichang.anjuke.com/community/"),
    ("xiangyang", "襄阳", "https://xiangyang.anjuke.com/community/"),
    ("yueyang", "岳阳", "https://yueyang.anjuke.com/community/"),
    ("jiujiang", "九江", "https://jiujiang.anjuke.com/community/"),
    ("ganzhou", "赣州", "https://ganzhou.anjuke.com/community/"),
    ("tangshan", "唐山", "https://tangshan.anjuke.com/community/"),
    ("qinhuangdao", "秦皇岛", "https://qinhuangdao.anjuke.com/community/"),
    ("handan", "邯郸", "https://handan.anjuke.com/community/"),
    ("mianyang", "绵阳", "https://mianyang.anjuke.com/community/"),
    ("yibin", "宜宾", "https://yibin.anjuke.com/community/"),
    ("nanchong", "南充", "https://nanchong.anjuke.com/community/"),
    ("zigong", "自贡", "https://zigong.anjuke.com/community/"),
    ("luzhou", "泸州", "https://luzhou.anjuke.com/community/"),
    ("zunyi", "遵义", "https://zunyi.anjuke.com/community/"),
    ("wuhu", "芜湖", "https://wuhu.anjuke.com/community/"),
    ("yangjiang", "阳江", "https://yangjiang.anjuke.com/community/"),
    ("jiangmen", "江门", "https://jiangmen.anjuke.com/community/"),
    ("zhanjiang", "湛江", "https://zhanjiang.anjuke.com/community/"),
    ("maoming", "茂名", "https://maoming.anjuke.com/community/"),
    ("qingyuan", "清远", "https://qingyuan.anjuke.com/community/"),
    ("jieyang", "揭阳", "https://jieyang.anjuke.com/community/"),
    ("yancheng", "盐城", "https://yancheng.anjuke.com/community/"),
    ("zhenjiang", "镇江", "https://zhenjiang.anjuke.com/community/"),
    ("taian", "泰安", "https://taian.anjuke.com/community/"),
    ("linyi", "临沂", "https://linyi.anjuke.com/community/"),
    ("rizhao", "日照", "https://rizhao.anjuke.com/community/"),
    ("jilin", "吉林", "https://jilin.anjuke.com/community/"),
    ("dandong", "丹东", "https://dandong.anjuke.com/community/"),
    ("yingkou", "营口", "https://yingkou.anjuke.com/community/"),
    ("baotou", "包头", "https://baotou.anjuke.com/community/"),
    ("hohhot", "呼和浩特", "https://huhehaote.anjuke.com/community/"),
    ("yinchuan", "银川", "https://yinchuan.anjuke.com/community/"),
    ("xining", "西宁", "https://xining.anjuke.com/community/"),
    ("lasa", "拉萨", "https://lasa.anjuke.com/community/"),
    ("urumqi", "乌鲁木齐", "https://wulumuqi.anjuke.com/community/"),
]


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"completed": [], "current": None, "total_scraped": 0, "total_saved": 0}


def save_progress(p):
    PROGRESS_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2))


async def _has_captcha(page):
    try:
        return "验证" in (await page.title())
    except Exception:
        return True


async def wait_captcha(page, timeout=120):
    for _ in range(timeout // 3):
        await asyncio.sleep(3)
        try:
            if not await _has_captcha(page):
                return True
        except Exception:
            pass
    return False


async def scrape_listing(page, url, max_pages=10):
    """Scrape up to max_pages of community listings."""
    all_comms = []
    seen = set()
    for pg in range(1, max_pages + 1):
        page_url = url if pg == 1 else f"{url.rstrip('/')}/p{pg}/"
        print(f"    [{now_str()}] p{pg}")
        try:
            await page.goto(page_url, wait_until="networkidle", timeout=30000)
        except Exception:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(2, 4))

        if await _has_captcha(page):
            print(f"    [!] Captcha — waiting...")
            if not await wait_captcha(page):
                print(f"    Skipping page (timeout)")
                continue
            await asyncio.sleep(2)

        links = await page.evaluate("""() => {
            const links = [];
            document.querySelectorAll('a[href*="/community/view/"]').forEach(a => {
                const href = a.getAttribute('href');
                if (href && /\\/community\\/view\\/\\d+$/.test(href))
                    links.push({url: a.href, text: a.textContent.trim()});
            });
            return links;
        }""")

        new_cnt = 0
        for link in links:
            cid_m = re.search(r"/community/view/(\d+)", link["url"])
            if not cid_m: continue
            cid = cid_m.group(1)
            if cid in seen: continue
            seen.add(cid)
            text = link["text"]
            name_m = re.match(r"^(\S+)", text)
            name = name_m.group(1) if name_m else ""
            price_m = re.search(r"(\d{3,6})\s*元/m", text)
            price = int(price_m.group(1)) if price_m else None
            year_m = re.search(r"(\d{4})年", text)
            year = int(year_m.group(1)) if year_m else None
            listing_m = re.search(r"二手房\((\d+)\)", text)
            lc = int(listing_m.group(1)) if listing_m else None
            all_comms.append({
                "name": name, "url": link["url"],
                "community_id_anjuke": cid,
                "avg_price": price, "listing_count": lc, "year_built": year,
            })
            new_cnt += 1
        print(f"    p{pg}: {new_cnt} new (total {len(all_comms)})")
        if new_cnt == 0:
            break
        if pg < max_pages:
            await asyncio.sleep(random.randint(*LISTING_PAUSE))
    return all_comms


async def scrape_detail(page, c):
    url = c.get("url", "")
    if not url: return c
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            return c
    await asyncio.sleep(2)

    if await _has_captcha(page):
        if not await wait_captcha(page, 60):
            return c

    result = dict(c)
    full_text = await page.evaluate("() => document.body?.innerText || ''")

    # Coords
    loc = await page.evaluate("""() => {
        const m = document.querySelector('meta[name="location"]');
        return m ? m.getAttribute('content') || '' : '';
    }""")
    coord_m = re.search(r"coord=([\d.]+),([\d.]+)", loc)
    if coord_m:
        result["coordinate_lng"] = float(coord_m.group(1))
        result["coordinate_lat"] = float(coord_m.group(2))

    for key, pat in [
        ("year_built", r"竣工时间\s*(\d{4})"),
        ("total_units", r"总户数\s*(\d+)"),
        ("floor_area_ratio", r"容积率\s*([\d.]+)"),
        ("green_ratio", r"绿化率\s*([\d.]+)"),
        ("property_fee", r"物业费\s*([\d.]+)"),
    ]:
        m = re.search(pat, full_text)
        if not m: continue
        val = m.group(1).strip()
        if key in ("year_built", "total_units"):
            d = re.search(r"(\d+)", val)
            if d: result[key] = int(d.group(1))
        elif key in ("floor_area_ratio", "green_ratio", "property_fee"):
            d = re.search(r"(\d+\.?\d*)", val)
            if d:
                try: result[key] = float(d.group(1))
                except ValueError: pass

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
    for cn, en in [("开发商", "developer"), ("物业公司", "property_mgmt"), ("小区地址", "address")]:
        if cn in js_info: result[en] = js_info[cn]

    if not result.get("avg_price"):
        pm = re.search(r"(\d{3,6})\s*元/[平㎡]", full_text)
        if pm: result["avg_price"] = int(pm.group(1))
    sm = re.search(r"在售房源[：:]?\s*(\d+)\s*套", full_text)
    if sm: result["on_sale_count"] = int(sm.group(1))
    rm = re.search(r"在租房源[：:]?\s*(\d+)\s*套", full_text)
    if rm: result["on_rent_count"] = int(rm.group(1))

    result["data_updated"] = now_str()
    if any(result.get(k) for k in ["year_built", "developer", "property_mgmt", "coordinate_lng"]):
        result["detail_scraped_at"] = now_str()

    fields = sum(1 for k in ["year_built","developer","property_mgmt","coordinate_lng","avg_price","on_sale_count"] if result.get(k))
    print(f"    {c['name']}: {fields}/6" + (f" coord({result['coordinate_lng']:.4f},{result['coordinate_lat']:.4f})" if result.get("coordinate_lng") else ""))
    return result


def save_to_db(communities, region_id):
    create_tables()
    conn = get_db()
    saved = 0
    for c in communities:
        cid = c.get("community_id", "")
        if not cid:
            aid = c.get("community_id_anjuke", "")
            cid = f"{region_id}_{aid}" if aid else f"{region_id}_{c.get('name','')}"
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
            print(f"    DB err {c.get('name')}: {e}")
    conn.commit()
    conn.close()
    return saved


async def run_city(page, region_id, city_name, url):
    print(f"\n{'='*60}")
    print(f"[{now_str()}] City: {city_name} ({region_id})")
    print(f"  URL: {url}")
    print(f"{'='*60}")

    print(f"\n  [Phase 1] Listing...")
    communities = await scrape_listing(page, url)
    print(f"  Found {len(communities)} communities")
    if not communities:
        return {"region_id": region_id, "scraped": 0, "saved": 0}

    print(f"\n  [Phase 2] Details ({len(communities)} pages)...")
    for i, c in enumerate(communities):
        try:
            communities[i] = await scrape_detail(page, c)
        except Exception as e:
            print(f"    Error: {e}")
        if (i > 0 and i % 10 == 0) or i == len(communities) - 1:
            save_to_db(communities[:i+1], region_id)
            print(f"    [saved {i+1}/{len(communities)}]")
        if i < len(communities) - 1:
            await asyncio.sleep(random.randint(*DETAIL_PAUSE))

    saved = save_to_db(communities, region_id)
    print(f"\n  Done: {city_name} — {saved}/{len(communities)}")
    return {"region_id": region_id, "scraped": len(communities), "saved": saved}


async def main():
    create_tables()

    progress = load_progress()
    completed = set(progress.get("completed", []))

    pending = [(rid, name, url) for rid, name, url in NEW_CITIES if rid not in completed]

    print(f"[{now_str()}] CubeMini City Expansion Crawler")
    print(f"  Done: {len(completed)} cities, Pending: {len(pending)} cities")
    print("=" * 60)

    if not pending:
        print("All cities done!")
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

        for region_id, city_name, url in pending:
            result = await run_city(page, region_id, city_name, url)
            completed.add(region_id)
            progress["completed"] = sorted(completed)
            progress["total_scraped"] = progress.get("total_scraped", 0) + result["scraped"]
            progress["total_saved"] = progress.get("total_saved", 0) + result["saved"]
            save_progress(progress)

            if len(pending) > 1:
                cooldown = random.randint(*CITY_COOLDOWN)
                print(f"\n  Cooldown: {cooldown//60}min...")
                await asyncio.sleep(cooldown)

        try:
            state = await context.storage_state()
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception:
            pass
        await browser.close()

    print(f"\n{'='*60}")
    print(f"[{now_str()}] Session done. {len(completed)} cities, {progress['total_scraped']} scraped")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
