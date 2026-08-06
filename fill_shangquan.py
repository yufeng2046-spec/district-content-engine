"""
Fill shangquan_id for existing communities by visiting shangquan listing pages.
For each shangquan, extract community links → match by Anjuke ID → update DB.
1,708 pages instead of 26,970.
"""
import asyncio, json, random, re, sys, time
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db.connection import get_db
from data.scrapers.stealth import STEALTH_JS

BASE_DIR = Path(__file__).resolve().parent
_LEGACY_STATE = BASE_DIR / "anjuke_state.json"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def _resolve_state(city_slug: str = "") -> Path:
    """Per-city state file with legacy fallback."""
    if city_slug:
        pc = BASE_DIR / f"anjuke_state_{city_slug}.json"
        if pc.exists():
            return pc
    return _LEGACY_STATE

# Extract Anjuke community ID from detail URL: /community/view/204300/
ANJUKE_ID_RE = re.compile(r'/view/(\d+)/')


async def _humanize(page, intensity: str = "light"):
    """Brief human-like interaction."""
    try:
        vp = page.viewport_size or {"width": 1440, "height": 900}
        w, h = vp["width"], vp["height"]
        scroll_y = random.randint(60, min(250, h - 100))
        await page.evaluate(f"window.scrollBy({{top: {scroll_y}, behavior: 'smooth'}})")
        await asyncio.sleep(random.uniform(0.3, 0.7))
        mx = random.randint(w // 4, w * 3 // 4)
        my = random.randint(80, h - 80)
        await page.mouse.move(mx, my, steps=random.randint(2, 4))
        await asyncio.sleep(random.uniform(0.2, 0.4))
    except Exception:
        pass


async def _wait_for_captcha(page, city_hint: str, timeout_seconds: int = 120) -> bool:
    """Wait for user to solve captcha."""
    print(f"  🔐 验证码！请在 Chrome 窗口中手动完成...")
    start = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start) < timeout_seconds:
        await asyncio.sleep(2)
        try:
            title = await page.title()
            if "验证" not in title:
                has_links = await page.evaluate(
                    "() => document.querySelectorAll('a[href*=\"/community/view/\"]').length > 0"
                )
                if has_links:
                    print(f"  ✅ 验证码已通过")
                    return True
        except Exception:
            pass
    print(f"  ⏰ 验证码超时")
    return False


async def extract_community_ids_from_page(page) -> list[str]:
    """Extract Anjuke community IDs from listing page cards."""
    ids = await page.evaluate("""() => {
        var ids = [];
        var links = document.querySelectorAll('a[href*="/community/view/"]');
        for (var i = 0; i < links.length; i++) {
            var href = links[i].getAttribute('href');
            var m = href.match(/\\/view\\/(\\d+)\\//);
            if (m) {
                ids.push(m[1]);
            }
        }
        return ids;
    }""")
    return ids


async def process_shangquan(page, conn, shangquan_id: str, sq_name: str, sq_url: str,
                            region_hint: str, city: str = "") -> tuple[int, int]:
    """Visit one shangquan listing page, match communities, update DB. Returns (found, matched).

    city: 安居客城市 slug (e.g. 'beijing'/'shanghai'), 用于限定匹配范围.
          必须限定城市, 否则 LIKE 匹配会跨城市误配 (历史 bug).
    """
    print(f"    {sq_name} ({shangquan_id[:50]}...)")

    try:
        await page.goto(sq_url, wait_until="networkidle", timeout=20000)
    except Exception:
        try:
            await page.goto(sq_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f"      ❌ Page load error: {e}")
            return (0, 0)

    await asyncio.sleep(random.uniform(1.5, 2.5))
    await _humanize(page, "light")

    # Captcha check
    try:
        title = await page.title()
        if "验证" in title:
            solved = await _wait_for_captcha(page, sq_name)
            if not solved:
                return (0, 0)
            try:
                await page.goto(sq_url, wait_until="networkidle", timeout=20000)
            except Exception:
                await page.goto(sq_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
    except Exception:
        pass

    # Extract community IDs from this shangquan page
    anjuke_ids = await extract_community_ids_from_page(page)

    if not anjuke_ids:
        return (0, 0)

    # Match to our DB and update
    # ⚠️ 修复历史 bug: 原先用 `community_id LIKE '%_{ajk_id}'` —
    #   SQL LIKE 里 `_` 是通配符(匹配任意单字符), 导致跨城市后缀误配
    #   (如上海 ID 405678 会匹配成都 ID 1405678)。
    #   修复: ① 转义下划线为字面量 (ESCAPE '\'); ② 限定 city_id 城市。
    if not city:
        city = shangquan_id.split("_")[0]  # 兜底: 从 shangquan_id 提取城市
    matched = 0
    for ajk_id in anjuke_ids:
        result = conn.execute(
            """UPDATE communities SET shangquan_id = ?
               WHERE shangquan_id IS NULL AND city_id = ?
                 AND community_id LIKE ? ESCAPE '\\'""",
            (shangquan_id, city, f"%\\_{ajk_id}"),
        ).rowcount
        matched += result

    if matched > 0:
        conn.commit()

    return (len(anjuke_ids), matched)


async def main(limit: int = 0):
    conn = get_db()

    # Get all shangquans with their city info
    shangquans = conn.execute(f"""
        SELECT s.shangquan_id, s.name, s.url, s.city, d.city_name, d.name as district_name
        FROM shangquans s
        JOIN districts d ON s.district_id = d.district_id
        ORDER BY
            CASE d.city
                WHEN 'yangling' THEN 1
                WHEN 'langfang' THEN 2
                WHEN 'shenzhen' THEN 3
                WHEN 'guangzhou' THEN 4
                WHEN 'xa' THEN 5
                WHEN 'chengdu' THEN 6
                WHEN 'shanghai' THEN 7
                WHEN 'datong' THEN 8
                WHEN 'beijing' THEN 9
                ELSE 10
            END,
            d.city, s.name
        {'LIMIT ' + str(limit) if limit > 0 else ''}
    """).fetchall()

    total_sq = len(shangquans)
    already_filled = conn.execute(
        "SELECT COUNT(*) FROM communities WHERE shangquan_id IS NOT NULL"
    ).fetchone()[0]

    print(f"=" * 60)
    print(f"Fill shangquan — {total_sq} shangquans to process")
    print(f"Already filled: {already_filled:,} / {conn.execute('SELECT COUNT(*) FROM communities').fetchone()[0]:,}")
    print(f"=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            storage_state=str(_resolve_state()) if _resolve_state().exists() else None,
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        total_found = 0
        total_matched = 0
        processed = 0
        captcha_count = 0

        for sq_id, sq_name, sq_url, city, city_name, district_name in shangquans:
            processed += 1
            print(f"\n[{processed}/{total_sq}] {city_name} {district_name} → {sq_name}")

            found, matched = await process_shangquan(
                page, conn, sq_id, sq_name, sq_url, f"{city_name}_{district_name}", city=city
            )
            total_found += found
            total_matched += matched

            if found == 0 and matched == 0:
                captcha_count += 1
                if captcha_count >= 3:
                    print(f"\n  ⚠️  {captcha_count} consecutive empty results — possible captcha wall")
                    print(f"  Waiting 30s before continuing...")
                    await asyncio.sleep(30)
                    captcha_count = 0
            else:
                captcha_count = 0

            # Progress
            still_null = conn.execute(
                "SELECT COUNT(*) FROM communities WHERE shangquan_id IS NULL"
            ).fetchone()[0]
            print(f"      Found {found:>3} | Matched {matched:>3} | "
                  f"Done {total_matched:>6,} | Remaining {still_null:>6,}")

            # Delay between shangquans (human-like pace)
            delay = random.uniform(1.5, 3.5)
            await asyncio.sleep(delay)

        # Save updated state
        try:
            state = await context.storage_state()
            _LEGACY_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception:
            pass
        await browser.close()

    # Final stats
    final_filled = conn.execute(
        "SELECT COUNT(*) FROM communities WHERE shangquan_id IS NOT NULL"
    ).fetchone()[0]
    still_null = conn.execute(
        "SELECT COUNT(*) FROM communities WHERE shangquan_id IS NULL"
    ).fetchone()[0]

    print(f"\n{'=' * 60}")
    print(f"Done!")
    print(f"  Shangquans processed: {processed}/{total_sq}")
    print(f"  Communities matched:  {total_matched:,}")
    print(f"  Final filled:         {final_filled:,}/{final_filled + still_null:,}")
    print(f"  Still NULL:           {still_null:,}")
    print(f"{'=' * 60}")

    conn.close()


if __name__ == "__main__":
    limit = 0
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
    asyncio.run(main(limit=limit))
