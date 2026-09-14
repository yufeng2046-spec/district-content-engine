"""
Discover all shangquan (商圈) URLs for a city from Anjuke.
Outputs shangquan_{city}.json for use with scrape_anjuke.py --shangquan all.

First-principles fix:
  1. District slug validation — reject structural non-districts (single-char, filter params)
  2. Click-to-load — for cities where shangquan links are AJAX-loaded, click each district tab
"""
import asyncio, json, sys, re, random
from collections import Counter
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.scrapers.stealth import STEALTH_JS

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = BASE_DIR / "anjuke_state.json"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# ── Slugs that are NOT real districts ──
# Single letters used as Anjuke filter/param shortcuts:
#   m=价格, f=房龄, s=地铁, w=物业, o=排序, p=分页
# Plus known functional path segments
INVALID_DISTRICT_SLUGS = {
    # Single-letter filter params
    'm', 'f', 's', 'w', 'o', 'p',
    # Functional pages
    'view', 'search', 'suggest', 'all', 'new', 'hot', 'map',
    # Generic terms (not district names)
    'community', 'loupan', 'ershoufang', 'xinfang', 'zufang',
    'list', 'detail', 'index', 'page', 'props',
    # Non-district pages
    'duibi', 'compare', 'pk', 'vs',
    # Numeric
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
    '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20',
    '20', '21', '22', '23', '24', '25', '26', '27', '28', '29', '30',
}

# Regex that matches known district slug patterns:
#   - Chinese pinyin: chaoyang, pudong, xuhui (multi-letter, lowercase)
#   - Pinyin with abbreviation: longhuaq, guangmingx (ends with q/x for 区/新区)
#   - Longer names: tianfuxinqu, jingkaiqux
#   NOT matched: single-letter (m, f), double-letter abbreviations that aren't places
VALID_DISTRICT_PATTERN = re.compile(r'^[a-z]{2,}[a-z]*$')


def _is_valid_district_slug(slug: str) -> bool:
    """Validate that a URL path segment looks like a real district slug."""
    if not slug:
        return False
    slug_lower = slug.lower()
    if slug_lower in INVALID_DISTRICT_SLUGS:
        return False
    if not VALID_DISTRICT_PATTERN.match(slug_lower):
        return False
    # Reject slugs that are pure repeated letters (e.g. 'aa', 'bbb')
    if len(set(slug_lower)) == 1 and len(slug_lower) > 1:
        return False
    return True


async def _humanize(page, intensity: str = "light") -> None:
    """Brief human-like interaction to reduce bot fingerprint."""
    try:
        vp = page.viewport_size or {"width": 1440, "height": 900}
        w, h = vp["width"], vp["height"]
        # One gentle scroll
        scroll_y = random.randint(80, min(300, h - 100))
        await page.evaluate(f"window.scrollBy({{top: {scroll_y}, behavior: 'smooth'}})")
        await asyncio.sleep(random.uniform(0.3, 0.8))
        # One mouse move
        mx = random.randint(w // 4, w * 3 // 4)
        my = random.randint(80, h - 80)
        await page.mouse.move(mx, my, steps=random.randint(2, 5))
        await asyncio.sleep(random.uniform(0.2, 0.5))
    except Exception:
        pass


def _make_extraction_js() -> str:
    """Generate JavaScript for shangquan extraction with semantic validation.

    Key insight: Anjuke embeds filter params into district URL paths, e.g.
    /community/pudong/m250/ (price filter in Pudong), which the old regex
    confused for a shangquan named 'm250'. We now validate BOTH the URL slug
    (must look like pinyin, not filter params) AND the link text (must look
    like a place name, not a price/age/subway filter).
    """
    # Single raw string block — no concatenation to avoid JS syntax issues
    return r"""(function() {
    function isValidShangquan(slug, text) {
        if (!slug || slug.length < 2) return false;
        if (/^[mfsowp]\d/.test(slug)) return false;
        if (/^\d+$/.test(slug)) return false;
        if (slug.length === 1) return false;
        var GENERIC = ['all','new','hot','view','search','suggest','list','page',
                       'loupan','ershoufang','xinfang','zufang','map',
                       'community','index','detail'];
        if (GENERIC.indexOf(slug) >= 0) return false;
        if (!text || text.length < 2 || text.length > 10) return false;
        if (/\d/.test(text)) return false;
        var FILTER_KW = ['万','年','地铁','物业','排序',
                         '热门','热度','视频','VR',
                         '有','附近','均价','涨跌',
                         '下一页','上一页','小区',
                         '页','套','元','以下','以上'];
        for (var i = 0; i < FILTER_KW.length; i++) {
            if (text.indexOf(FILTER_KW[i]) >= 0) return false;
        }
        return true;
    }

    function isValidDistrict(slug, text) {
        if (!slug || slug.length < 2) return false;
        if (/^[mfsowp]$/.test(slug)) return false;
        var BAD = ['all','new','hot','view','search','suggest','list','page',
                   'loupan','ershoufang','xinfang','zufang','map',
                   'community','index','detail','0','1','2','3','4','5',
                   '6','7','8','9','10','11','12','13','14','15','16','17',
                   '18','19','20','21','22','23','24','25','26','27','28','29','30'];
        if (BAD.indexOf(slug) >= 0) return false;
        if (text && text.length >= 2 && text.length <= 10 && !/[一-鿿]/.test(text)) return false;
        return true;
    }

    var districts = {};
    var links = document.querySelectorAll('a[href*="/community/"]');
    for (var i = 0; i < links.length; i++) {
        var a = links[i];
        var href = a.getAttribute('href');
        var text = a.textContent.trim();
        if (!text || text.length < 2 || text.length > 20) continue;

        var m = href.match(/\/community\/([a-z0-9]+)\/?(?:([a-z0-9_-]+)\/)?$/i);
        // Also match new Anjuke format: /community/<district>-q-<shangquan>/
        var m2 = href.match(/\/community\/([a-z0-9]+)-q-([a-z0-9_-]+)\/?/i);

        var district, shangquan;

        if (m2) {
            // New format: pudong-q-babaiban
            district = m2[1].toLowerCase();
            shangquan = m2[2].toLowerCase();
        } else if (m) {
            // Old format: chaoyang/wangjing or single district
            district = m[1].toLowerCase();
            shangquan = m[2] ? m[2].toLowerCase() : null;
        } else {
            continue;
        }

        if (!districts[district]) {
            if (!isValidDistrict(district, text)) continue;
            districts[district] = {name: text, shangquan: []};
        }
        if (shangquan && isValidShangquan(shangquan, text)) {
            var exists = districts[district].shangquan.some(function(s) { return s.url === href; });
            if (!exists) {
                districts[district].shangquan.push({
                    name: text,
                    url: href.indexOf('http') === 0 ? href : 'https://' + window.location.host + href
                });
            }
        }
    }
    return districts;
})()"""


async def _extract_static_shangquan(page, city_slug: str) -> dict:
    """Strategy A: Extract district→shangquan from already-rendered HTML.

    Works for cities where Anjuke server-renders the full hierarchy
    (Beijing, Chengdu, Xi'an, Datong).
    """
    return await page.evaluate(_make_extraction_js())


async def _debug_dump_links(page, label: str = "") -> None:
    """Debug helper: dump all community links on page, grouped by URL pattern."""
    links = await page.evaluate("""() => {
        var all = [];
        var links = document.querySelectorAll('a[href*="/community/"]');
        for (var i = 0; i < links.length; i++) {
            var a = links[i];
            var href = a.getAttribute('href');
            var text = a.textContent.trim();
            if (!text) continue;
            all.push({
                href: href,
                text: text
            });
        }
        return all;
    }""")
    if links:
        # Group by URL pattern
        from collections import Counter
        patterns = Counter()
        examples = {}
        for l in links:
            href = l['href']
            # Extract the path structure: /community/X/ or /community/X/Y/ or other
            parts = href.split('/community/')
            if len(parts) > 1:
                rest = parts[1].rstrip('/')
                segments = rest.split('/')
                if len(segments) == 1:
                    pat = 'DISTRICT_ONLY'
                elif len(segments) == 2:
                    pat = f'DIST/SQ'
                else:
                    pat = f'DEEPER({len(segments)})'
                patterns[pat] += 1
                if pat not in examples:
                    examples[pat] = (href[:80], l['text'])
            else:
                patterns['OTHER'] += 1

        print(f"    [DEBUG {label}] {len(links)} community links:")
        for pat, cnt in patterns.most_common():
            ex_href, ex_text = examples[pat]
            print(f"      {pat:15s}: {cnt:>3} links  e.g. {ex_href[:70]:70s} '{ex_text}'")


async def _click_and_extract_shangquan(page, city_slug: str, district_slug: str, district_name: str) -> list[dict]:
    """Strategy B: Click a district tab, wait for AJAX shangquan list, extract links.

    For cities where shangquan sub-links are only loaded dynamically
    (Shanghai, Guangzhou, Shenzhen).
    """
    shangquan_list = []

    # Try multiple selectors for the district tab element
    click_selectors = [
        f'a[href*="/community/{district_slug}/"]',
        f'a[href="/community/{district_slug}/"]',
        f'div[data-district="{district_slug}"]',
        f'li[data-district="{district_slug}"]',
    ]

    clicked = False
    for selector in click_selectors:
        try:
            element = await page.query_selector(selector)
            if element:
                await element.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(0.3, 0.6))
                await element.click(timeout=5000)
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        # Last resort: click by visible text
        try:
            element = page.get_by_text(district_name, exact=True).first
            if element:
                await element.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(0.3, 0.6))
                await element.click(timeout=5000)
                clicked = True
        except Exception:
            pass

    if not clicked:
        return shangquan_list

    # Wait for AJAX content to load
    await asyncio.sleep(random.uniform(1.5, 2.5))
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass

    # Extract shangquan links that appeared after clicking (use semantic validation)
    shangquan_list = await page.evaluate("""([distSlug]) => {
        function isValidShangquan(slug, text) {
            if (!slug || slug.length < 2) return false;
            if (/^[mfsowp]\\d/.test(slug)) return false;
            if (/^\\d+$/.test(slug)) return false;
            if (slug.length === 1) return false;
            var GENERIC = ['all','new','hot','view','search','suggest','list','page',
                           'loupan','ershoufang','xinfang','zufang','map',
                           'community','index','detail'];
            if (GENERIC.indexOf(slug) >= 0) return false;
            if (!text || text.length < 2 || text.length > 10) return false;
            if (/\\d/.test(text)) return false;
            var FILTER_KW = ['万','年','地铁','物业','排序',
                             '热门','热度','视频','VR',
                             '有','附近','均价','涨跌',
                             '下一页','上一页','小区',
                             '页','套','元','以下','以上'];
            for (var i = 0; i < FILTER_KW.length; i++) {
                if (text.indexOf(FILTER_KW[i]) >= 0) return false;
            }
            return true;
        }

        var results = [];
        var links = document.querySelectorAll('a[href*="/community/"]');

        for (var i = 0; i < links.length; i++) {
            var a = links[i];
            var href = a.getAttribute('href');
            var text = a.textContent.trim();
            if (!text || text.length < 2 || text.length > 20) continue;

            // Match both old and new URL formats
            // Old: /community/<district>/<shangquan>/
            var m1 = href.match(/\\/community\\/([a-z0-9]+)\\/([a-z0-9_-]+)\\/?/i);
            // New: /community/<district>-q-<shangquan>/
            var m2 = href.match(/\\/community\\/([a-z0-9]+)-q-([a-z0-9_-]+)\\/?/i);

            var hrefDistrict, shangquanSlug;

            if (m2) {
                hrefDistrict = m2[1].toLowerCase();
                shangquanSlug = m2[2].toLowerCase();
            } else if (m1) {
                hrefDistrict = m1[1].toLowerCase();
                shangquanSlug = m1[2].toLowerCase();
            } else {
                continue;
            }

            // Must belong to the district we clicked
            if (hrefDistrict !== distSlug) continue;

            if (isValidShangquan(shangquanSlug, text)) {
                var exists = results.some(function(s) { return s.url === href; });
                if (!exists) {
                    results.push({
                        name: text,
                        url: href.indexOf('http') === 0 ? href : 'https://' + window.location.host + href
                    });
                }
            }
        }

        return results;
    }""", [district_slug])

    return shangquan_list


async def _wait_for_captcha(page, city_name: str, timeout_seconds: int = 180) -> bool:
    """Wait for user to solve captcha in visible browser. Returns True if solved."""
    print(f"  🔐 验证码！请在 Chrome 窗口中手动完成验证...")
    print(f"     (等待最多 {timeout_seconds}s)")
    try:
        from captcha_notify import send_captcha_alert
        send_captcha_alert(city_name, page.url, "", "shangquan_discover")
    except Exception:
        pass

    start = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start) < timeout_seconds:
        await asyncio.sleep(2)
        try:
            title = await page.title()
            if "验证" not in title:
                # Check if page actually loaded content
                has_content = await page.evaluate(
                    "() => document.querySelectorAll('a[href*=\"/community/\"]').length > 5"
                )
                if has_content:
                    elapsed = int(asyncio.get_event_loop().time() - start)
                    print(f"  ✅ 验证码已通过 (耗时 {elapsed}s)")
                    return True
        except Exception:
            pass
    print(f"  ⏰ 验证码超时，跳过此城市")
    return False


async def discover_city(page, city_slug: str, city_name: str) -> dict:
    """Discover all district→shangquan URLs for a city.

    Uses a layered strategy:
      A) Extract statically from initial HTML (fast path, works for Beijing/Chengdu/etc.)
      B) Click each district tab to load shangquan dynamically (for Shanghai/Guangzhou/etc.)
    """
    print(f"\n{'='*50}")
    print(f"Discovering: {city_name} ({city_slug})")
    print(f"{'='*50}")

    url = f"https://{city_slug}.anjuke.com/community/"
    result = {"city": city_slug, "city_name": city_name, "districts": {}}

    # ── Load page ──
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  ❌ Page load error: {e}")
            return result

    await asyncio.sleep(3)
    await _humanize(page, "light")

    # ── Captcha check ──
    try:
        title = await page.title()
        if "验证" in title:
            solved = await _wait_for_captcha(page, city_name)
            if not solved:
                return result
            # After captcha solve, re-navigate to community page
            print(f"  🔄 Re-navigating to community page...")
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
    except Exception:
        pass

    # ═══════════════════════════════════════
    # Strategy A: Static extraction from rendered HTML
    # ═══════════════════════════════════════
    static_data = await _extract_static_shangquan(page, city_slug)

    # Filter to only valid district slugs
    districts = {}
    bad_slugs_removed = []
    for dslug, ddata in static_data.items():
        if _is_valid_district_slug(dslug):
            districts[dslug] = ddata
        else:
            bad_slugs_removed.append(dslug)

    if bad_slugs_removed:
        print(f"  🧹 Filtered {len(bad_slugs_removed)} non-district slugs: {bad_slugs_removed}")

    total_static_sq = sum(len(v.get('shangquan', [])) for v in districts.values())
    districts_with_sq = sum(1 for v in districts.values() if len(v.get('shangquan', [])) > 0)
    print(f"  Strategy A (static): {len(districts)} districts, {total_static_sq} shangquan"
          f" ({districts_with_sq} districts with shangquan)")

    # ═══════════════════════════════════════
    # Strategy B: Click-to-load for districts with 0 shangquan
    # ═══════════════════════════════════════
    need_click = [
        (dslug, ddata)
        for dslug, ddata in districts.items()
        if len(ddata.get('shangquan', [])) == 0
    ]

    if need_click:
        print(f"\n  Strategy B (click-to-load): {len(need_click)} districts need dynamic loading")

        for idx, (dslug, ddata) in enumerate(need_click):
            district_cn = ddata.get('name', dslug)
            print(f"    [{idx+1}/{len(need_click)}] Clicking {district_cn} ({dslug})...")

            try:
                sq_list = await _click_and_extract_shangquan(page, city_slug, dslug, district_cn)
                if sq_list:
                    districts[dslug]['shangquan'] = sq_list
                    print(f"      ✅ Found {len(sq_list)} shangquan")
                else:
                    print(f"      ⚠️  No shangquan found (may be a district with no sub-neighborhoods)")

                # Human-like pause between clicks to avoid triggering rate limits
                await asyncio.sleep(random.uniform(1.0, 2.0))

            except Exception as e:
                print(f"      ❌ Error: {e}")
                continue

        total_after_click = sum(len(v.get('shangquan', [])) for v in districts.values())
        print(f"  After Strategy B: {total_after_click} total shangquan")

    # ── Ensure URLs are absolute ──
    base_host = f"https://{city_slug}.anjuke.com"
    for dist_data in districts.values():
        for sq in dist_data.get('shangquan', []):
            if sq['url'].startswith('/'):
                sq['url'] = f"{base_host}{sq['url']}"

    # ── Remove empty districts (keep only those with shangquan) ──
    districts_with_data = {
        dslug: ddata
        for dslug, ddata in districts.items()
        if len(ddata.get('shangquan', [])) > 0
    }
    empty_count = len(districts) - len(districts_with_data)
    if empty_count > 0:
        empty_names = [districts[d].get('name', d) for d in districts if d not in districts_with_data]
        print(f"  ℹ️  {empty_count} districts with 0 shangquan dropped: {empty_names}")

    total_sq = sum(len(v.get('shangquan', [])) for v in districts_with_data.values())
    print(f"  ✅ Final: {len(districts_with_data)} districts, {total_sq} shangquan")

    result["districts"] = districts_with_data
    return result


async def main():
    if len(sys.argv) > 1:
        cities = [(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1])]
    else:
        # Default: scan all cities that don't already have valid shangquan data
        cities = [
            # Priority: fix the broken ones
            ("shanghai", "上海"),
            ("guangzhou", "广州"),
            ("shenzhen", "深圳"),
            # New cities to discover
            ("hangzhou", "杭州"),
            ("wuhan", "武汉"),
            ("nanjing", "南京"),
            ("tianjin", "天津"),
            ("suzhou", "苏州"),
            ("chongqing", "重庆"),
            ("changsha", "长沙"),
            ("zhengzhou", "郑州"),
            ("dongguan", "东莞"),
            ("qingdao", "青岛"),
            ("shenyang", "沈阳"),
            ("ningbo", "宁波"),
            ("kunming", "昆明"),
            ("wuxi", "无锡"),
            ("foshan", "佛山"),
            ("hefei", "合肥"),
            ("dalian", "大连"),
            ("fuzhou", "福州"),
            ("xiamen", "厦门"),
            ("haerbin", "哈尔滨"),
            ("jinan", "济南"),
            ("wenzhou", "温州"),
            ("nanning", "南宁"),
        ]

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        success_count = 0
        for city_slug, city_name in cities:
            out_file = DATA_DIR / f"shangquan_{city_slug}.json"

            # Check existing data quality (skip if already has real shangquan)
            if out_file.exists():
                existing = json.loads(out_file.read_text())
                districts = existing.get('districts', {})
                # Count only valid districts with shangquan
                real_sq = 0
                for dslug, ddata in districts.items():
                    if _is_valid_district_slug(dslug):
                        real_sq += len(ddata.get('shangquan', []))
                if real_sq > 10:
                    print(f"\n  {city_name}: already has {real_sq} valid shangquan, skip")
                    success_count += 1
                    continue
                else:
                    print(f"\n  {city_name}: has only {real_sq} valid shangquan, re-discovering...")

            result = await discover_city(page, city_slug, city_name)

            total_sq = sum(len(v.get('shangquan', [])) for v in result['districts'].values())
            if total_sq > 0:
                out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                print(f"  💾 Saved: {out_file} ({total_sq} shangquan)")
                success_count += 1
            else:
                print(f"  ❌ No shangquan found for {city_name}")

        # Save updated browser state
        try:
            state = await context.storage_state()
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception:
            pass
        await browser.close()

    print(f"\n{'='*50}")
    print(f"Done. {success_count}/{len(cities)} cities with shangquan data.")
    print(f"Check {DATA_DIR}/shangquan_*.json")


if __name__ == "__main__":
    asyncio.run(main())
