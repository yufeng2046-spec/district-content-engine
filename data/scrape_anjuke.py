"""
Anjuke community scraper — fully autonomous edition.
Uses stealth JS + VL captcha solver (Bailian) for zero-human-intervention scraping.

Usage:
    PYTHONPATH=. python3 data/scrape_anjuke.py --region chengdu_wuhou --max 5
    PYTHONPATH=. python3 data/scrape_anjuke.py --region chengdu_wuhou --shangquan 万达
    PYTHONPATH=. python3 data/scrape_anjuke.py --region chengdu_wuhou --shangquan all
    PYTHONPATH=. python3 data/scrape_anjuke.py --login                         (auto-login with VL)
    PYTHONPATH=. python3 data/scrape_anjuke.py --login --show                  (visible browser debug)
    PYTHONPATH=. python3 data/scrape_anjuke.py --login --manual                (human solves captcha)
    PYTHONPATH=. python3 data/scrape_anjuke.py --listings-only --max 100       (fast listing-only mode)
    PYTHONPATH=. python3 data/scrape_anjuke.py --state anjuke_state_beijing.json  (per-city state file)
    PYTHONPATH=. python3 data/scrape_anjuke.py --xvfb                         (virtual display, no captcha wait)

Auto-login: if no saved state exists, the scraper auto-logins with headless browser + VL captcha
solver. Use --manual if VL fails: opens visible browser, you solve captcha, press Enter.
Storage state persists across runs.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# Force line-buffered output for real-time monitoring (even without PYTHONUNBUFFERED)
sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    get_region, USER_AGENT, DEFAULT_REGION, BAILIAN_KEY,
    PAGE_DELAY_MIN_MS, PAGE_DELAY_MAX_MS,
    DETAIL_DELAY_MIN_MS, DETAIL_DELAY_MAX_MS,
    RPM_SOFT_CAP, RPM_HARD_CAP,
)

# ── Rate limiter ──────────────────────────────────────────
_request_times: list[float] = []

def _rate_limit() -> None:
    """Enforce RPM_HARD_CAP: sleep if we've made too many requests in the last 60s."""
    global _request_times
    now = time.time()
    _request_times = [t for t in _request_times if now - t < 60]
    if len(_request_times) >= RPM_HARD_CAP:
        wait_s = _request_times[0] + 60 - now + random.uniform(1, 3)
        if wait_s > 0:
            time.sleep(wait_s)
    _request_times.append(time.time())
from db.connection import get_db
from db.schema import create_tables
from captcha_notify import send_captcha_alert
from data.captcha_solver import solve_captcha, denorm_coord, solve_slider_with_opencv, generate_drag_trajectory
import base64 as _base64
import cv2 as _cv2
import numpy as _np
import urllib.request as _urllib_request

BASE_DIR = Path(__file__).resolve().parent.parent
COOKIES_FILE = BASE_DIR / "anjuke_cookies.json"
_LEGACY_STATE_FILE = BASE_DIR / "anjuke_state.json"  # backward compat fallback

# Module-level mutable state — set by main() based on --state flag or city auto-detect
_ACTIVE_STATE_FILE: Path = _LEGACY_STATE_FILE
_ACTIVE_COOKIES_FILE: Path = COOKIES_FILE


def get_state_file() -> Path:
    """Return the active state file (per-city or legacy default)."""
    return _ACTIVE_STATE_FILE


def _resolve_state_for_city(city_slug: str) -> Path:
    """Resolve per-city state file path. Falls back to legacy if per-city doesn't exist."""
    if not city_slug:
        return _LEGACY_STATE_FILE
    per_city = BASE_DIR / f"anjuke_state_{city_slug}.json"
    if per_city.exists():
        return per_city
    if _LEGACY_STATE_FILE.exists():
        return _LEGACY_STATE_FILE
    return per_city  # will be created


# Module-level proxy setting (set by --proxy CLI arg)
_PROXY_SERVER: str | None = None

def _browser_launch_args() -> list[str]:
    """Base Chromium args, with optional proxy."""
    args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    if _PROXY_SERVER:
        args.append(f"--proxy-server={_PROXY_SERVER}")
    return args

from data.scrapers.stealth import STEALTH_JS


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


async def _solve_yidun_word_order(page) -> tuple[list[tuple[int, int]], str] | None:
    """Enhanced YiDun word-order solver using direct bg image + enhancement + VL.

    Downloads the YiDun bg image directly, enhances it with CLAHE+bilateral+sharpen,
    sends to VL for character identification in bg-image pixel space, then maps to viewport.

    Returns ([(vp_x, vp_y), ...], idiom) or None if failed.
    """
    import requests as _requests
    try:
        info = await page.evaluate("""() => {
            const bgimg = document.querySelector('.yidun_bg-img');
            if (!bgimg) return null;
            const r = bgimg.getBoundingClientRect();
            return {src: bgimg.src, vpX: Math.round(r.x), vpY: Math.round(r.y),
                    w: Math.round(r.width), h: Math.round(r.height)};
        }""")
        if not info:
            return None

        bg_path = str(BASE_DIR / "data" / "yidun_debug" / "bg_live.png")
        _urllib_request.urlretrieve(info["src"], bg_path)
        img = _cv2.imread(bg_path)
        if img is None:
            return None
        ih, iw = img.shape[:2]
        # Scale factor from natural image pixels → CSS display pixels
        scale_x = info['w'] / iw if iw > 0 else 1
        scale_y = info['h'] / ih if ih > 0 else 1
        print(f"    YiDun bg: {iw}x{ih} (CSS: {info['w']}x{info['h']}) at vp({info['vpX']},{info['vpY']}) scale=({scale_x:.2f},{scale_y:.2f})")

        # ── Enhance image ──
        gray = _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)
        clahe = _cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        denoised = _cv2.bilateralFilter(enhanced, 9, 75, 75)
        kernel_sharpen = _np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = _cv2.filter2D(denoised, -1, kernel_sharpen)
        enhanced_color = _cv2.cvtColor(sharpened, _cv2.COLOR_GRAY2BGR)

        # Draw 4x2 grid overlay
        grid_cols, grid_rows = 4, 2
        cell_w = iw // grid_cols
        cell_h = ih // grid_rows
        grid_img = enhanced_color.copy()
        for i in range(1, grid_cols):
            x = i * cell_w
            _cv2.line(grid_img, (x, 0), (x, ih), (0, 255, 0), 1)
        for i in range(1, grid_rows):
            y = i * cell_h
            _cv2.line(grid_img, (0, y), (iw, y), (0, 255, 0), 1)
        for row in range(grid_rows):
            for col in range(grid_cols):
                _cv2.putText(grid_img, f"({col},{row})", (col * cell_w + 4, row * cell_h + 14),
                            _cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 255, 0), 1)

        # Encode both versions
        _, grid_buf = _cv2.imencode(".png", grid_img)
        grid_b64 = _base64.b64encode(grid_buf.tobytes()).decode()
        _, enhanced_buf = _cv2.imencode(".png", enhanced_color)
        enhanced_b64 = _base64.b64encode(enhanced_buf.tobytes()).decode()

        prompt = f"""This is a YiDun captcha image ({iw}x{ih} pixels). A green grid divides it into 8 cells (4 columns × 2 rows). Exactly 4 cells contain one Chinese character each — the other 4 cells are empty/noise.

STEP 1 — Identify each character:
For each grid cell, look carefully at the shape, strokes, and structure. Determine the EXACT character — do not guess a similar-looking character. If a cell has no character, mark it null.

STEP 2 — Determine the phrase:
The 4 characters form a common Chinese idiom (成语) or phrase. From the 4 identified characters, figure out the correct reading order.

Return ONLY a JSON object with the idiom and each character's pixel coordinates:
{{"idiom":"四字成语","chars":[{{"char":"确","x":50,"y":80}},{{"char":"认","x":150,"y":60}},{{"char":"每","x":250,"y":90}},{{"char":"字","x":180,"y":110}}]}}"""

        def _vl_call(b64_img, prompt_text):
            r = _requests.post(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                headers={"Authorization": f"Bearer {BAILIAN_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "qwen-vl-plus",
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}},
                        {"type": "text", "text": prompt_text},
                    ]}],
                    "max_tokens": 500, "temperature": 0.05,
                },
                timeout=30,
            )
            return r.json()["choices"][0]["message"]["content"].strip()

        raw = _vl_call(enhanced_b64, prompt)
        print(f"    VL: {raw[:150]}")

        # Parse single VL response
        def _parse_vl(raw_text):
            raw_text = raw_text.strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                raw_text = re.sub(r"\s*```$", "", raw_text)
            try:
                return json.loads(raw_text)
            except json.JSONDecodeError:
                m = re.search(r'\{[^{}]*"idiom"[^{}]*\}', raw_text, re.DOTALL)
                if m:
                    return json.loads(m.group())
                return None

        result = _parse_vl(raw)
        if not result or len(result.get("chars", [])) < 4:
            print(f"    Failed to get 4 chars from VL")
            return None

        idiom = result.get("idiom", "?")
        chars = result["chars"][:4]
        print(f"    Idiom: {idiom}")

        # Convert to element-relative CSS coordinates (for .yidun_bg-img click)
        clicks = []
        for c in chars:
            if "x" in c and "y" in c:
                # Direct pixel coordinates from VL result → scale to CSS
                bg_x = int(c["x"])
                bg_y = int(c["y"])
            else:
                # Grid cell → pixel center
                bg_x = int((c.get("col", 0) + 0.5) * cell_w)
                bg_y = int((c.get("row", 0) + 0.5) * cell_h)
            elem_x = int(bg_x * scale_x)
            elem_y = int(bg_y * scale_y)
            clicks.append((elem_x, elem_y))
            print(f"      {c['char']} bg({bg_x},{bg_y}) → elem({elem_x},{elem_y})")

        return clicks, idiom

    except Exception as e:
        print(f"    _solve_yidun_word_order error: {e}")
        return None


async def auto_solve_captcha(page, screenshot_path: str | None = None, max_rounds: int = 3) -> bool:
    """Take screenshot, send to VL model, execute captcha action. Handles YiDun word_order, slider, click, text input. Returns True if solved."""
    import tempfile
    if not BAILIAN_KEY:
        return False

    tmp_path = screenshot_path or tempfile.mktemp(suffix=".png")
    try:
        # ── Pre-check: trigger YiDun captcha if 58.com anti-bot page ──
        await _trigger_yidun_if_needed(page)

        for round_num in range(max_rounds):
            # Re-trigger YiDun on rounds 2+ in case modal was dismissed
            if round_num > 0:
                await _trigger_yidun_if_needed(page)

            await page.screenshot(path=tmp_path, full_page=False)

            # Pass page title as context so VL knows this is a captcha page
            page_context = ""
            try:
                page_context = await page.title()
            except Exception:
                pass

            result = solve_captcha(tmp_path, api_key=BAILIAN_KEY, page_context=page_context)
            action_type = result.get("type", "unknown")
            desc = result.get("description", "")
            print(f"    VL captcha [round {round_num+1}]: {action_type} — {desc[:80]}")

            if action_type == "none":
                return True

            if action_type == "unknown":
                _save_debug_screenshot(tmp_path, f"unknown_r{round_num+1}")
                return False

            viewport = page.viewport_size or {"width": 1440, "height": 900}
            w, h = viewport["width"], viewport["height"]

            if action_type == "word_order":
                # Use enhanced bg-image solver for precise coordinates
                yidun_result = await _solve_yidun_word_order(page)
                if yidun_result:
                    clicks, idiom = yidun_result
                    print(f"    Clicking {len(clicks)} chars on .yidun_bgimg: {idiom}")
                    bg_elem = page.locator('.yidun_bgimg')
                    for i, (ex, ey) in enumerate(clicks):
                        # Click on the bg image element at relative position
                        await bg_elem.click(position={'x': ex, 'y': ey},
                                           delay=random.randint(100, 300))
                        await page.wait_for_timeout(random.randint(400, 700))
                    await page.wait_for_timeout(3000)
                    if not await _has_captcha(page):
                        return True
                    continue

                # Fallback to VL screenshot-based clicks
                clicks = result.get("clicks", [])
                if not clicks or len(clicks) < 2:
                    print(f"    VL returned insufficient word_order clicks: {clicks}")
                    continue

                print(f"    Clicking {len(clicks)} characters in order: {desc}")
                for i, (nx, ny) in enumerate(clicks):
                    px, py = denorm_coord(nx, ny, w, h)
                    print(f"      [{i+1}] ({px}, {py})")
                    await page.mouse.click(px, py)
                    await page.wait_for_timeout(random.randint(300, 700))

                await page.wait_for_timeout(2000)
                if not await _has_captcha(page):
                    return True
                # word_order may need another round if the order was wrong
                continue

            if action_type == "click":
                tx, ty = result.get("target_norm", [500, 500])
                px, py = denorm_coord(tx, ty, w, h)
                # Try coordinate click
                await page.mouse.click(px, py)
                await page.wait_for_timeout(1500)
                if not await _has_captcha(page):
                    return True

                # Coordinate click failed — try clicking common verification button selectors
                for sel in ['button', 'a.btn', '.btn', '[class*="verify"]', '[class*="captcha"]',
                            '[id*="verify"]', '[id*="captcha"]', '.verify-btn', '#btnSubmit',
                            '[class*="button"]', 'input[type="submit"]', 'input[type="button"]']:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=500):
                            await btn.click(timeout=2000)
                            await page.wait_for_timeout(2000)
                            if not await _has_captcha(page):
                                return True
                    except Exception:
                        continue

                # Try click-and-hold on the coordinate (some 58.com buttons require holding)
                await page.mouse.move(px, py)
                await page.mouse.down()
                await page.wait_for_timeout(1000)
                await page.mouse.up()
                await page.wait_for_timeout(1500)
                # Don't return — let next round check what happened after the click

            elif action_type == "drag":
                # Use OpenCV for precise slider gap detection
                ocv_result = solve_slider_with_opencv(tmp_path, viewport)
                if ocv_result and ocv_result.get("drag_pixels", 0) > 15:
                    sx = ocv_result["slider_x"]
                    sy = ocv_result["slider_y"]
                    dist = ocv_result["drag_pixels"]
                    trajectory = generate_drag_trajectory(dist, duration_ms=random.randint(900, 1500))

                    # Execute human-like drag with trajectory
                    await page.mouse.move(sx, sy)
                    await page.wait_for_timeout(random.randint(100, 300))
                    await page.mouse.down()
                    await page.wait_for_timeout(random.randint(50, 150))
                    prev_t = 0
                    for step_x, step_y, step_t in trajectory[1:]:
                        dt = max(5, step_t - prev_t)
                        await page.mouse.move(sx + step_x, sy + step_y, steps=1)
                        await page.wait_for_timeout(dt)
                        prev_t = step_t
                    await page.wait_for_timeout(random.randint(100, 300))
                    await page.mouse.up()
                    await page.wait_for_timeout(2500)
                    if not await _has_captcha(page):
                        return True
                    # OpenCV drag failed — fall through to VL-based attempt below

                # Fallback: VL coordinate-based drag
                fx, fy = result.get("from_norm", [300, 500])
                tx, ty = result.get("to_norm", [700, 500])
                fx_px, fy_px = denorm_coord(fx, fy, w, h)
                tx_px, ty_px = denorm_coord(tx, ty, w, h)
                await page.mouse.move(fx_px, fy_px)
                await page.mouse.down()
                await page.mouse.move(tx_px, ty_px, steps=20)
                await page.wait_for_timeout(500)
                await page.mouse.up()
                await page.wait_for_timeout(2000)
                if not await _has_captcha(page):
                    return True

            elif action_type == "input":
                text = result.get("text", "")
                if text:
                    try:
                        for sel in ['input[type="text"]', 'input:not([type])', 'input.captcha-input',
                                    'input[placeholder*="验证码"]', 'input[name*="captcha"]']:
                            try:
                                await page.fill(sel, text, timeout=2000)
                                break
                            except Exception:
                                continue
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(2000)
                        if not await _has_captcha(page):
                            return True
                    except Exception:
                        pass

            # If we get here, the action might not have fully solved the captcha
            # Continue to next round to check for secondary challenge
            if await _has_captcha(page) and round_num < max_rounds - 1:
                continue

        # All rounds exhausted
        if await _has_captcha(page):
            _save_debug_screenshot(tmp_path, f"failed_after_{max_rounds}_rounds")
            return False
        return True

    except Exception as e:
        print(f"    VL solver error: {e}")
        return False
    finally:
        if not screenshot_path and Path(tmp_path).exists():
            Path(tmp_path).unlink()


def _save_debug_screenshot(tmp_path, tag):
    """Save a copy of the screenshot to data/ for debugging."""
    import shutil
    debug_dir = BASE_DIR / "data" / "captcha_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = debug_dir / f"{ts}_{tag}.png"
    shutil.copy(tmp_path, dest)
    print(f"    Debug screenshot saved: {dest}")


async def _trigger_yidun_if_needed(page) -> bool:
    """If the page has 58.com's #btnSubmit AND YiDun modal is not already visible, click to trigger it."""
    try:
        # Check if YiDun modal is already open — don't re-trigger if it is
        modal = page.locator(".yidun_modal")
        if await modal.is_visible(timeout=500):
            return False  # Already open, don't re-trigger

        btn = page.locator("#btnSubmit")
        if await btn.is_visible(timeout=1000):
            await btn.click(timeout=3000)
            await page.wait_for_timeout(3000)
            try:
                await page.wait_for_selector(".yidun_modal", state="visible", timeout=5000)
                print(f"    YiDun modal appeared after clicking #btnSubmit")
            except Exception:
                print(f"    YiDun modal did not appear after clicking #btnSubmit")
            return True
    except Exception:
        pass
    return False


async def _humanize(page, intensity: str = "medium") -> None:
    """Simulate human browsing: scroll, mouse move, hover. Reduces bot fingerprint."""
    vp = page.viewport_size or {"width": 1440, "height": 900}
    w, h = vp["width"], vp["height"]

    # 1. Random scroll — humans rarely stay at top of page
    scroll_steps = random.randint(2, 5) if intensity == "long" else random.randint(1, 3)
    for _ in range(scroll_steps):
        scroll_y = random.randint(100, max(200, h - 100))
        await page.evaluate(f"window.scrollBy({{top: {scroll_y}, behavior: 'smooth'}})")
        await asyncio.sleep(random.uniform(0.5, 2.0))

    # 2. Random mouse movement — move to plausible page elements
    for _ in range(random.randint(1, 3)):
        mx = random.randint(w // 4, w * 3 // 4)
        my = random.randint(80, h - 80)
        await page.mouse.move(mx, my, steps=random.randint(3, 8))
        await asyncio.sleep(random.uniform(0.2, 0.8))

    # 3. Sometimes scroll back up (re-reading)
    if random.random() < 0.3:
        await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        await asyncio.sleep(random.uniform(0.5, 1.5))

    # 4. Long-read mode: sometimes pause significantly
    if intensity == "long" and random.random() < 0.4:
        await asyncio.sleep(random.uniform(2, 6))

    # 5. Occasional micro-pause (simulates looking at something)
    if random.random() < 0.5:
        await asyncio.sleep(random.uniform(0.3, 1.2))


async def _has_captcha(page) -> bool:
    """Check if page still shows captcha."""
    try:
        title = await page.title()
        if "验证" in title:
            return True
        # Also check for common captcha elements
        content = await page.content()
        if "验证码" in content or "滑块" in content or "captcha" in content.lower():
            return True
        return False
    except Exception:
        return True  # Assume captcha if can't check


async def _wait_for_human_captcha(page, region_name: str, url: str, page_type: str = "detail",
                                    show_browser: bool = True) -> bool:
    """Captcha state machine: pause → notify → wait for human → resume.
    Returns True if captcha cleared, False if timeout (10 min)."""
    import tempfile
    tmp = tempfile.mktemp(suffix=".png")
    try:
        await page.screenshot(path=tmp, full_page=False)
    except Exception:
        tmp = "screenshot_failed"

    if show_browser:
        print(f"    ⚠️  验证码 — 请在 Chrome 窗口中手动完成验证")
    else:
        print(f"    ⚠️  验证码 (headless) — 等待自动恢复...")

    # Send Feishu notification after 30s of waiting
    notified = False
    for i in range(200):  # 10 minutes max (200 × 3s)
        await asyncio.sleep(3)
        try:
            if not await _has_captcha(page):
                elapsed = (i + 1) * 3
                print(f"    ✓ 验证码已清除 ({elapsed}s)")
                return True
        except Exception:
            pass
        # Notify via Feishu after 30s
        if not notified and i >= 10:
            try:
                send_captcha_alert(region_name, url, tmp, page_type)
            except Exception:
                pass
            notified = True

    print(f"    ⏰ 验证码等待超时 (10min)")
    return False


async def login_and_save_cookies(anjuke_url: str, headless: bool = True, manual: bool = False) -> bool:
    """Login to Anjuke. In manual mode, user solves captcha in visible browser.

    Manual mode: opens visible browser, waits for user to solve captcha and press Enter.
    Auto mode: headless browser with VL captcha solving.
    """
    mode = "Manual" if manual else "Auto-login"
    is_headless = headless and not manual  # manual mode forces visible browser
    print(f"{mode} (headless={'yes' if is_headless else 'no'})...")

    if manual:
        print("  ⚠️  MANUAL MODE: Solve the captcha in the browser window.")
        print("  Waiting for the page to clear captcha automatically...")

    for attempt in range(1 if manual else 3):
        if manual:
            print(f"  Opening browser...")
        else:
            print(f"  Login attempt {attempt+1}/3...")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=is_headless,
                    args=_browser_launch_args(),
                )
                context = await browser.new_context(
                    user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
                )
                page = await context.new_page()
                await page.add_init_script(STEALTH_JS)

                await page.goto(anjuke_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)
                title = await page.title()
                print(f"  Title: {title}")

                if manual:
                    # Poll until captcha is solved or timeout (5 minutes)
                    import asyncio as _asyncio
                    print("  ─────────────────────────────────────────────")
                    print("  Browser is open. Solve the captcha manually.")
                    print("  Waiting for captcha to clear...")
                    print("  ─────────────────────────────────────────────")
                    for wait_i in range(60):  # 5 minutes max
                        await _asyncio.sleep(5)
                        try:
                            title = await page.title()
                            has_c = await _has_captcha(page)
                            if not has_c:
                                print(f"  ✓ Captcha cleared! Title: {title}")
                                break
                            if wait_i % 6 == 0:  # Print status every 30s
                                print(f"  ...still waiting ({wait_i * 5}s)")
                        except Exception:
                            pass
                    else:
                        print(f"  Timed out waiting for captcha. Saving whatever state we have...")

                    cookies = await context.cookies()
                    save_cookies(cookies)
                    await context.storage_state(path=str(get_state_file()))
                    print(f"  Storage state saved to {get_state_file()}")
                    await browser.close()
                    return True

                if "验证" in title or "captcha" in title.lower():
                    print("  Captcha detected — solving with VL...")
                    solved = await auto_solve_captcha(page, max_rounds=3)
                    if solved:
                        await page.wait_for_timeout(3000)
                        title = await page.title()
                        if "验证" not in title and "captcha" not in title.lower():
                            print(f"  VL solved! Title: {title}")
                            cookies = await context.cookies()
                            save_cookies(cookies)
                            await context.storage_state(path=str(get_state_file()))
                            print(f"  Storage state saved to {get_state_file()}")
                            await browser.close()
                            return True
                        else:
                            print(f"  VL action done but captcha remains. Retrying...")
                    else:
                        print(f"  VL could not solve, retrying...")
                else:
                    # No captcha — page loaded clean
                    cookies = await context.cookies()
                    save_cookies(cookies)
                    await context.storage_state(path=str(get_state_file()))
                    print(f"  No captcha. Storage state saved.")
                    await browser.close()
                    return True

                await browser.close()
        except Exception as e:
            print(f"  Login attempt {attempt+1} error: {e}")

        if attempt < (0 if manual else 2):
            wait_s = (attempt + 1) * 10
            print(f"  Waiting {wait_s}s before retry...")
            import asyncio as _asyncio
            await _asyncio.sleep(wait_s)

    if not manual:
        print("  All login attempts failed.")
    return False


async def scrape_listing_page(page, url: str, show_browser: bool = False) -> list[dict]:
    """Scrape a single listing page, return parsed communities."""
    _rate_limit()
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    # Light human scroll — listing pages need less interaction
    await _humanize(page, intensity="short")

    title = await page.title()
    if "验证" in title:
        if not show_browser:
            # Headless: don't waste time waiting. Save state, return empty.
            print("  🔒 Listing captcha (headless) — skipping page")
            try:
                state = await page.context.storage_state()
                get_state_file().write_text(json.dumps(state, ensure_ascii=False, indent=2))
            except Exception:
                pass
            return []
        cleared = await _wait_for_human_captcha(
            page, "listing", url, "listing", show_browser=show_browser)
        if cleared:
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            title = await page.title()
        else:
            print("  Captcha timeout on listing page, skipping")
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


async def scrape_listing(page, base_url: str, max_communities: int = 0, show_browser: bool = False) -> list[dict]:
    """Scrape all listing pages. max_communities=0 means unlimited."""
    all_communities = []
    seen_ids = set()

    # Normalize: ensure base_url ends with /
    if not base_url.endswith("/"):
        base_url = base_url + "/"

    consecutive_empty = 0
    consecutive_dup = 0       # 连续 0 新增页 — 防"周边桶"翻页死循环(东莞桶曾翻到 92 页)
    DUP_STOP = 12             # 连续 12 页全重复视为数据已穷尽, 停止分页
    for pg in range(1, 200):  # cap at 200 pages (5000 communities)
        url = base_url if pg == 1 else f"{base_url}p{pg}/"
        print(f"\n  Page {pg}: {url}")

        page_communities = await scrape_listing_page(page, url, show_browser=show_browser)
        if not page_communities:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                print(f"  Page {pg}: empty (2 in a row), stopping pagination")
                break
            # Try to recover from captcha — re-login and retry
            print(f"  Page {pg}: empty — may be captcha, waiting and retrying...")
            await page.wait_for_timeout(random.randint(5000, 10000))
            continue
        else:
            consecutive_empty = 0

        new_count = 0
        for c in page_communities:
            cid = c["community_id_anjuke"]
            if cid not in seen_ids:
                seen_ids.add(cid)
                all_communities.append(c)
                new_count += 1

        if new_count == 0:
            consecutive_dup += 1
            if consecutive_dup >= DUP_STOP:
                print(f"  Page {pg}: {DUP_STOP} consecutive all-duplicate pages, stopping pagination")
                break
        else:
            consecutive_dup = 0

        print(f"  Page {pg}: {new_count} new communities (running total: {len(all_communities)})")

        if max_communities > 0 and len(all_communities) >= max_communities:
            all_communities = all_communities[:max_communities]
            print(f"  Reached max_communities={max_communities}, stopping")
            break

        # Small delay between pages
        await page.wait_for_timeout(random.randint(2000, 4000))

    return all_communities


async def scrape_all_shangquan(page, region_id: str, city_slug: str, district_name: str | None,
                               max_communities: int = 0, show_browser: bool = False,
                               district_display_name: str = "",
                               listings_only: bool = False) -> tuple[int, int]:
    """Scrape all shangquan for a district. Returns (total_scraped, total_saved).

    Supports resume: tracks completed shangquans in data/progress_{region_id}.json.
    Saves browser state after each shangquan for crash safety.
    In headless mode: exits after 3 consecutive captcha failures (saves progress).
    listings_only: skip detail pages — only (re)assign shangquan_id non-destructively.
    """
    sq_file = BASE_DIR / "data" / f"shangquan_{city_slug}.json"
    if not sq_file.exists():
        print(f"  No shangquan file: {sq_file}")
        return (0, 0)

    sq_data = json.loads(sq_file.read_text())
    districts = sq_data.get("districts", {})

    # ═══ Progress tracking (resume support) ═══
    PROGRESS_FILE = BASE_DIR / "data" / f"progress_{region_id}.json"
    completed_ids: set = set()
    if PROGRESS_FILE.exists():
        try:
            prev = json.loads(PROGRESS_FILE.read_text())
            completed_ids = set(prev.get("completed", []))
            if completed_ids:
                print(f"  📋 Resume: {len(completed_ids)} shangquans already completed, will skip")
        except Exception:
            pass

    def _save_progress():
        """Save progress JSON. State save is async — handled separately."""
        try:
            PROGRESS_FILE.write_text(json.dumps({
                "region_id": region_id,
                "completed": sorted(completed_ids),
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False, indent=2))
        except Exception:
            pass

    async def _save_state():
        """Save browser storage state for crash safety + CubeMini sync."""
        try:
            state = await page.context.storage_state()
            get_state_file().write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception:
            pass

    # Collect all (district_name, shangquan, shangquan_id) triples to scrape
    tasks = []
    skipped = 0
    for dist_name, dist_info in districts.items():
        # Match by slug (e.g. "xicheng"), by display name (e.g. "西城"),
        # or by JSON key (e.g. "西城"), or by the info's name/slug field
        dist_info_name = dist_info.get("name", "")
        dist_info_slug = dist_info.get("slug", "")
        if district_name and dist_name != district_name and dist_name != district_display_name and dist_info_name != district_name and dist_info_name != district_display_name and dist_info_slug != district_name:
            continue
        for sq in dist_info.get("shangquan", []):
            sq_url = sq["url"]
            sq_slug = ""
            parts = sq_url.rstrip("/").split("/")
            if len(parts) >= 2:
                last = parts[-1]
                if "-q-" in last:
                    sq_slug = last.split("-q-", 1)[-1]
                else:
                    sq_slug = last
            # 用 district 的 slug (英文) 而不是 JSON key (中文), 保持 shangquan_id 格式统一
            dist_slug = dist_info.get("slug") or dist_name
            shangquan_id = f"{city_slug}_{dist_slug}_{sq_slug}" if sq_slug else ""
            if shangquan_id in completed_ids:
                skipped += 1
                continue
            tasks.append((dist_name, sq["name"], sq_url, shangquan_id))

    if skipped:
        print(f"  ⏭️  Skipped {skipped} already-completed shangquans")

    if not tasks:
        print(f"  ✅ All {len(completed_ids)} shangquans already completed for {district_name or 'all districts'}!")
        return (0, 0)

    print(f"\n{'='*50}")
    print(f"Batch shangquan scrape — {len(tasks)} shangquans for {district_name or 'all districts'}")
    if completed_ids:
        print(f"  ({len(completed_ids)} already done, {len(tasks)} remaining)")
    print(f"{'='*50}")

    total_scraped = 0
    total_saved = 0
    consecutive_empty = 0
    total_empty = 0      # 商圈数: 完全没爬到小区的
    captcha_count = 0    # 商圈数: 撞验证码的
    HEADLESS_CAPTCHA_EXIT = 3  # After N consecutive empty results in headless, save & exit

    for idx, (dist_name, sq_name, sq_url, shangquan_id) in enumerate(tasks):
        print(f"\n--- [{idx+1}/{len(tasks)}] {dist_name} / {sq_name} ---")
        print(f"  URL: {sq_url}")

        communities = await scrape_listing(page, sq_url, max_communities, show_browser=show_browser)
        total_scraped += len(communities)

        # Pass known shangquan_id to each community
        if shangquan_id:
            for c in communities:
                c["shangquan_id"] = shangquan_id

        if communities:
            # Phase 1: Save listing data immediately
            save_to_db(communities, region_id, listings_only=listings_only)

            if listings_only:
                saved = len(communities)
                total_saved += saved
                print(f"  [listings-only] Saved {saved}/{len(communities)} (shangquan_id updated, total: {total_saved})")
                consecutive_empty = 0
            else:
                # Phase 2: Scrape detail pages for this shangquan
                print(f"  Scraping details for {len(communities)} communities...")
                detail_i = 0
                while detail_i < len(communities):
                    c = communities[detail_i]
                    try:
                        communities[detail_i] = await scrape_detail(page, c, show_browser=show_browser)
                        delay_s = random.uniform(DETAIL_DELAY_MIN_MS, DETAIL_DELAY_MAX_MS) / 1000
                        await page.wait_for_timeout(int(delay_s * 1000))
                        detail_i += 1
                    except Exception as e:
                        print(f"    Detail error for {c['name']}: {e}")
                        detail_i += 1

                    if (detail_i > 0 and detail_i % 10 == 0) or detail_i == len(communities):
                        save_to_db(communities[:detail_i], region_id)

                saved = len(communities)
                total_saved += saved
                print(f"  Saved {saved}/{len(communities)} with details (total: {total_saved})")
                consecutive_empty = 0

            # ✅ Mark complete + save progress after each successful shangquan
            completed_ids.add(shangquan_id)
            _save_progress()
            await _save_state()

        else:
            print(f"  No communities found")
            total_empty += 1
            consecutive_empty += 1

            # Headless mode: captcha blocks are fatal — exit early with progress saved
            if not show_browser:
                print(f"  🔒 Headless captcha (#{consecutive_empty}/{HEADLESS_CAPTCHA_EXIT}) — "
                      f"listing blocked, likely captcha wall")
                if consecutive_empty >= HEADLESS_CAPTCHA_EXIT:
                    print(f"  ❌ {HEADLESS_CAPTCHA_EXIT} consecutive empty in headless — "
                          f"saving progress and exiting.")
                    print(f"  💡 Fix: run with --show locally to solve captcha, then sync state to headless.")
                    _save_progress()
                    await _save_state()
                    break
            else:
                # Visible browser: attempt relogin for empty results
                if consecutive_empty >= 1:
                    print(f"  ⚠️  Empty shangquan (#{consecutive_empty}) — attempting relogin...")
                    from config import get_region as _gr
                    _region = _gr(region_id)
                    _login_url = _region.get("anjuke_url", sq_url)
                    _ok = await login_and_save_cookies(_login_url, headless=True)
                    if _ok:
                        print(f"  Relogin succeeded, resuming batch...")
                        consecutive_empty = 0
                        from data.scrape_anjuke import load_cookies as _lc
                        _cookies = _lc()
                        if _cookies:
                            await page.context.add_cookies(_cookies)
                    else:
                        print(f"  Relogin failed, continuing with existing session...")
                        if consecutive_empty >= 5:
                            print(f"  ⚠️  5 consecutive empty with failed relogin, stopping batch")
                            _save_progress()
                            await _save_state()
                            break

        # Delay between shangquans to avoid rate limiting
        if idx < len(tasks) - 1:
            delay_s = random.uniform(8, 15)
            print(f"  Waiting {delay_s:.0f}s...")
            await page.wait_for_timeout(int(delay_s * 1000))

    # ── 区域健康摘要 (供 check_crawl.py / 人工判断静默失败) ──
    empty_pct = total_empty / len(tasks) * 100 if tasks else 0
    health = "✅" if empty_pct < 20 else ("⚠️" if empty_pct < 50 else "❌")
    print(f"\nBatch complete: scraped {total_scraped}, saved {total_saved}")
    print(f"  {health} 健康摘要: 商圈 {len(tasks)} | 空商圈 {total_empty} ({empty_pct:.0f}%) | 小区 {total_scraped}")
    if empty_pct >= 20:
        print(f"  💡 空商圈比例偏高 — 可能区匹配失败(datong类)或验证码墙, 建议 python3 check_crawl.py --region {region_id}")
    return (total_scraped, total_saved)


def _parse_property_basic(full_text: str) -> dict:
    """从详情页 innerText 解析同页基本信息 → property_basic_json 内容。

    基本信息是连续文本: "物业类型 住宅权属类别 商品房住宅竣工时间 2016年、2017年..."
    每个字段值取到下一个已知标签为止 (标签前允许换行/空格)。
    原为 scrape_detail 内联, 2026-09-08 重构为独立函数供 --fix-json 复用。
    """
    _nxt = r"(?=\s*(?:物业类型|权属类别|竣工时间|产权年限|总户数|总建面积|容积率|绿化率|建筑类型|所属商圈|统一供暖|供水供电|停车位|停车费|车位管理费|物业费|物业公司|小区地址|开发商|小区问答|小区解读|$))"
    basic_info = {}
    _basic_pats = [
        ("property_type",     r"物业类型\s*(.{1,8}?)"),
        ("ownership",         r"权属类别\s*(.{1,16}?)"),
        ("rights_years",      r"产权年限\s*(\d+)年"),
        ("building_area",     r"总建面积\s*([\d.]+)㎡"),
        ("heating",           r"统一供暖\s*([^\n]{1,5}?)"),
        ("water_electric",    r"供水供电\s*([^\n]{1,10}?)"),
        ("parking_fee",       r"停车费\s*([^\n]{1,40}?)"),
        ("parking_mgmt_fee",  r"车位管理费\s*([^\n]{1,20}?)"),
    ]
    for key, pat in _basic_pats:
        m = re.search(pat + _nxt, full_text)
        if m and m.group(1).strip():
            basic_info[key] = m.group(1).strip().rstrip("。，")
    # 竣工时间: 可能多个年份 (2016年、2017年、2021年)
    ym = re.search(r"竣工时间\s*([\d、\s年]+?)" + _nxt, full_text)
    if ym:
        years = re.findall(r"(\d{4})", ym.group(1))
        if years:
            basic_info["years_built"] = [int(y) for y in years]
    return basic_info


def _parse_interpretation(full_text: str) -> dict:
    """从详情页 innerText 解析小区解读(经纪人写的分段评述) → content dict。

    每段: "标题\n\n<一个段落>" (段落到空行为止, 不依赖后续是否为已知标签)。
    原为 scrape_detail 内联, 2026-09-08 重构为独立函数供 --fix-json 复用。
    """
    interpretation = {}
    for sec, key in [("轨道交通", "transport"), ("小区户型", "layout"),
                     ("小区设施", "facilities"), ("生活配套", "life_support"),
                     ("小区不足", "shortcomings")]:
        m = re.search(re.escape(sec) + r"\s*\n\s*\n([\s\S]+?)(?=\n\s*\n|$)", full_text)
        if m:
            txt = re.sub(r"\s+", " ", m.group(1)).strip()
            if txt and len(txt) < 600:
                interpretation[key] = txt
    return interpretation


async def scrape_detail(page, community: dict, show_browser: bool = False) -> dict:
    """Scrape community detail page — full enrichment with amenities, trends, reviews."""
    url = community.get("url", "")
    if not url:
        # Fallback: search Anjuke for the community by name
        name = community.get("name", "")
        city_slug = community.get("city_slug", "chengdu")
        if not name:
            return community
        search_url = f"https://{city_slug}.anjuke.com/community/search/?q={name}"
        print(f"    🔍 Searching: {search_url}")
        _rate_limit()
        try:
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
        except Exception:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Try to extract community URL from search results
        found_url = await page.evaluate("""() => {
            const links = document.querySelectorAll('a[href*="/community/view/"]');
            for (const a of links) {
                const href = a.getAttribute('href');
                if (href && /\\/community\\/view\\/\\d+/.test(href)) {
                    return a.href;
                }
            }
            return '';
        }""")
        if found_url:
            url = found_url
            print(f"    ✓ Found via search: {url}")
        else:
            # Second attempt: try the suggest API via page navigation
            suggest_url = f"https://{city_slug}.anjuke.com/community/suggest/?q={name}"
            print(f"    Search page empty, trying suggest: {suggest_url}")
            await page.goto(suggest_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            found_url = await page.evaluate("""() => {
                const links = document.querySelectorAll('a[href*="/community/view/"]');
                for (const a of links) {
                    const href = a.getAttribute('href');
                    if (href && /\\/community\\/view\\/\\d+/.test(href)) {
                        return a.href;
                    }
                }
                return '';
            }""")
            if found_url:
                url = found_url
                print(f"    ✓ Found via suggest: {url}")
            else:
                print(f"    ❌ Could not find '{name}' on Anjuke, skipping")
                return community

    print(f"    Loading: {community['name']}")
    _rate_limit()
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"    Nav error: {e}")
            return community

    # Simulate human browsing before checking content
    await _humanize(page, intensity=random.choice(["short", "medium", "medium", "long"]))

    # Captcha check — human-in-the-loop state machine
    if await _has_captcha(page):
        if not show_browser:
            # Headless: don't waste 180s waiting. Save state, skip detail, continue.
            print(f"    🔒 Captcha (headless) — skipping detail, will retry later")
            save_cookies(await page.context.cookies())
            try:
                state = await page.context.storage_state()
                get_state_file().write_text(json.dumps(state, ensure_ascii=False, indent=2))
            except Exception:
                pass
            return community
        cleared = await _wait_for_human_captcha(
            page, community.get("name", "?"), url, "detail", show_browser=show_browser)
        if cleared:
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)
            except Exception:
                pass
        else:
            print(f"    Captcha timeout — saving state and pausing")
            # Save cookies so we can resume later
            save_cookies(await page.context.cookies())
            await page.context.storage_state(path=str(get_state_file()))
            # Return community without detail (can retry later)
            return community

    result = dict(community)

    # Track which core enrichment fields were missing before detail scrape
    _core_fields = [
        "year_built", "developer", "property_mgmt", "property_fee",
        "floor_area_ratio", "green_ratio", "coordinate_lng", "coordinate_lat",
    ]
    _filled_before = sum(1 for k in _core_fields if result.get(k))

    full_text = await page.evaluate("() => document.body?.innerText || ''")

    # ── 1. Coordinates from <meta name="location"> ──
    loc = await page.evaluate("""() => {
        const m = document.querySelector('meta[name="location"]');
        return m ? m.getAttribute('content') || '' : '';
    }""")
    coord_m = re.search(r"coord=([\d.]+),([\d.]+)", loc)
    if coord_m:
        result["coordinate_lng"] = float(coord_m.group(1))
        result["coordinate_lat"] = float(coord_m.group(2))

    # ── 2. Basic property info (text parsing) ──
    dense_matches = {
        "year_built": r"竣工时间\s*(\d{4})",
        "total_units": r"总户数\s*(\d+)",
        "floor_area_ratio": r"容积率\s*([\d.]+)",
        "green_ratio": r"绿化率\s*([\d.]+)",
        "property_fee": r"物业费\s*([\d.]+)",
        "building_types": r"建筑类型\s*(.+?)(?:所属商圈|统一供暖|供水|$)",
        "shangquan_name": r"所属商圈\s*(.+?)(?:\n|统一供暖|供水|$)",
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
            types = re.findall(r"(?:多层|小高层?|高层|塔楼|板楼|别墅|联排|独栋|洋房)", val)
            if types:
                result[key] = json.dumps(types, ensure_ascii=False)
        else:
            result[key] = val

    # ── 3+4. 同页基本信息 + 小区解读(重构为独立函数, 供 --fix-json 复用) ──
    basic_info = _parse_property_basic(full_text)
    if basic_info:
        result["property_basic_json"] = json.dumps(basic_info, ensure_ascii=False)
    interpretation = _parse_interpretation(full_text)
    if interpretation:
        result["community_interpretation_json"] = json.dumps(interpretation, ensure_ascii=False)

    # ── Resolve shangquan name → shangquan_id ──
    sq_name = result.pop("shangquan_name", None)
    if sq_name:
        result["shangquan_name"] = sq_name  # keep for debugging
        # Try direct name match in shangquans table
        try:
            conn = get_db()
            # 必须按城市限定 — 否则"光明"(深圳光明区)会匹配到北京顺义"光明"商圈,
            # 造成跨城 shangquan_id (validate S1 跨城检查曾抓到 13 条)
            _city = community.get("city_slug", "")
            if _city:
                row = conn.execute(
                    """SELECT shangquan_id FROM shangquans
                       WHERE name = ?
                         AND substr(shangquan_id, 1, instr(shangquan_id, '_') - 1) = ?
                       LIMIT 1""",
                    (sq_name, _city)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT shangquan_id FROM shangquans WHERE name = ? LIMIT 1",
                    (sq_name,)
                ).fetchone()
            conn.close()
            if row:
                result["shangquan_id"] = row["shangquan_id"]
        except Exception:
            pass

    # Developer / property mgmt / address from label-value pairs
    label_map = {"开发商": "developer", "物业公司": "property_mgmt", "小区地址": "address"}
    js_info = await page.evaluate("""() => {
        const data = {};
        document.querySelectorAll('.label').forEach(label => {
            const key = label.textContent.trim();
            const valueEl = label.nextElementSibling;
            if (valueEl && valueEl.classList.contains('value')) {
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

    # ── 3. Listing counts (在售/在租) ──
    sale_m = re.search(r"在售房源[：:]?\s*(\d+)\s*套", full_text)
    if sale_m:
        result["on_sale_count"] = int(sale_m.group(1))

    rent_m = re.search(r"在租房源[：:]?\s*(\d+)\s*套", full_text)
    if rent_m:
        result["on_rent_count"] = int(rent_m.group(1))

    # ── 4. Surrounding amenities (周边配套) ──
    surrounding = await _scrape_surrounding(page, full_text)
    if surrounding:
        result["surrounding_json"] = json.dumps(surrounding, ensure_ascii=False)

    # ── 5. Price trend (房价走势) ──
    trend = _parse_price_trend(full_text)
    if trend:
        result["price_trend_json"] = json.dumps(trend, ensure_ascii=False)

    # ── 6. Agent reviews (小区解读/小区优点) ──
    reviews = _parse_reviews(full_text)
    if reviews:
        result["community_review"] = json.dumps(reviews, ensure_ascii=False)

    # Features / selling points
    features_m = re.search(r"【小区[优点特]】(.+?)(?:【|$)", full_text)
    if features_m and not result.get("features"):
        result["features"] = json.dumps(
            [f.strip() for f in features_m.group(1).split("，") if f.strip()],
            ensure_ascii=False,
        )

    result["data_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Only mark detail_scraped_at if the detail page actually enriched core fields
    _filled_after = sum(1 for k in _core_fields if result.get(k))
    if _filled_after > _filled_before:
        result["detail_scraped_at"] = result["data_updated"]

    fields_got = sum(1 for k in [
        "year_built", "developer", "property_mgmt", "property_fee",
        "floor_area_ratio", "green_ratio", "parking_ratio", "total_units",
        "building_types", "avg_price", "coordinate_lng", "on_sale_count",
        "on_rent_count", "surrounding_json", "price_trend_json", "community_review",
    ] if result.get(k))
    coord_str = ""
    if result.get("coordinate_lng"):
        coord_str = f"  Coord: {result['coordinate_lng']}, {result['coordinate_lat']}"
    print(f"    Fields: {fields_got}/16{coord_str}  Sale:{result.get('on_sale_count','-')} Rent:{result.get('on_rent_count','-')}")

    return result


def _valid_name(name: str) -> bool:
    """Sanity-check an extracted community name: 2-20 CJK-ish chars, not a page header."""
    name = (name or "").strip()
    if not name:
        return False
    if len(name) < 2 or len(name) > 20:
        return False
    if not re.search(r"[一-鿿]", name):
        return False
    if name in ("小区详情", "房产", "安居客", "首页", "二手房"):
        return False
    return True


async def _extract_name(page) -> str:
    """Extract community name from a loaded anjuke detail page.

    Priority: h1 → og:title/<title> → breadcrumb. Returns "" if nothing passes
    _valid_name. Used by --fix-names to recover names whose listing-page parse
    failed (B3) without re-scraping the full detail.
    """
    try:
        # 1. h1 — cleanest on anjuke detail pages
        name = (await page.evaluate(
            "() => document.querySelector('h1')?.textContent?.trim() || ''") or "").strip()
        if not _valid_name(name):
            name = ""
        if not name:
            # 2. og:title / <title>: "{name}小区详情_{name}二手房..." → 取第一段
            t = (await page.evaluate("""() => {
                const og = document.querySelector('meta[property="og:title"]');
                return (og && og.getAttribute('content')) || document.title || '';
            }""") or "").strip()
            t = re.split(r"[|_｜\-—]", t)[0]
            t = re.sub(r"(小区详情|小区怎么样|房价走势|二手房|怎么样|房价|详情).*$", "", t).strip()
            if _valid_name(t):
                name = t
        if not name:
            # 3. breadcrumb last segment
            crumb = (await page.evaluate("""() => {
                const els = document.querySelectorAll('.breadcrumb a, .crumb a, .location a');
                return els.length ? els[els.length - 1].textContent.trim() : '';
            }""") or "").strip()
            if _valid_name(crumb):
                name = crumb
        return re.sub(r"\s+", "", name or "")
    except Exception:
        return ""


async def scrape_names(page, communities: list[dict], show_browser: bool = False) -> int:
    """Fix empty community names by visiting detail pages and extracting the name.

    Only updates the `name` column — never touches existing detail data (avoids
    the INSERT OR REPLACE data-loss risk on a captcha timeout).
    """
    fixed = 0
    for c in communities:
        url = c.get("url", "")
        if not url:
            print(f"    ⏭  {c['community_id']}: 无数字 anjuke ID，跳过")
            continue
        print(f"    Loading: {c['community_id']}")
        _rate_limit()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"    Nav error: {e}")
                continue
        await _humanize(page, intensity=random.choice(["short", "medium", "short"]))

        if await _has_captcha(page):
            if not show_browser:
                print(f"    🔒 Captcha (headless) — skipping")
                save_cookies(await page.context.cookies())
                continue
            cleared = await _wait_for_human_captcha(page, c["community_id"], url, "detail",
                                                    show_browser=show_browser)
            if cleared:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass
            else:
                print(f"    Captcha timeout — saving state and pausing")
                save_cookies(await page.context.cookies())
                try:
                    await page.context.storage_state(path=str(get_state_file()))
                except Exception:
                    pass
                continue

        name = await _extract_name(page)
        if name:
            conn = get_db()
            conn.execute("UPDATE communities SET name=? WHERE community_id=?",
                         (name, c["community_id"]))
            conn.commit()
            conn.close()
            print(f"    ✓ 名称恢复: {c['community_id']} → {name}")
            fixed += 1
        else:
            print(f"    ✗ 未能提取名称: {c['community_id']}")
    return fixed


async def scrape_json(page, communities: list[dict], show_browser: bool = False) -> int:
    """历史存量补 property_basic_json / community_interpretation_json (--fix-json)。

    08-11 前旧代码爬的社区缺这两个字段, 需重访详情页解析。**只 UPDATE 这两列**,
    绝不 INSERT OR REPLACE 整行 → 验证码超时也不会抹既有数据(与 --fix-names 同理)。
    轻量: 不跑周边/趋势/评价等富解析, 只取 full_text 解 2 字段, 提速 ~2x。
    """
    fixed = 0
    for c in communities:
        url = c.get("url", "")
        if not url:
            print(f"    ⏭  {c['community_id']}: 无数字 anjuke ID，跳过")
            continue
        print(f"    Loading: {c['community_id']}")
        _rate_limit()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"    Nav error: {e}")
                continue
        await _humanize(page, intensity=random.choice(["short", "medium", "short"]))

        if await _has_captcha(page):
            if not show_browser:
                print(f"    🔒 Captcha (headless) — skipping")
                save_cookies(await page.context.cookies())
                continue
            cleared = await _wait_for_human_captcha(page, c["community_id"], url, "detail",
                                                    show_browser=show_browser)
            if cleared:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass
            else:
                print(f"    Captcha timeout — saving state and pausing")
                save_cookies(await page.context.cookies())
                try:
                    await page.context.storage_state(path=str(get_state_file()))
                except Exception:
                    pass
                continue

        try:
            full_text = await page.evaluate("() => document.body?.innerText || ''")
        except Exception:
            continue
        updates = {}
        basic = _parse_property_basic(full_text)
        if basic:
            updates["property_basic_json"] = json.dumps(basic, ensure_ascii=False)
        interp = _parse_interpretation(full_text)
        if interp:
            updates["community_interpretation_json"] = json.dumps(interp, ensure_ascii=False)

        if updates:
            sets = ", ".join(f"{k}=?" for k in updates)
            conn = get_db()
            conn.execute(
                f"UPDATE communities SET {sets} WHERE community_id=?",
                (*updates.values(), c["community_id"]),
            )
            conn.commit()
            conn.close()
            fixed += 1
            print(f"    ✓ JSON 回填: {c['community_id']}"
                  f" (basic={'✓' if 'property_basic_json' in updates else '✗'}"
                  f" interp={'✓' if 'community_interpretation_json' in updates else '✗'})")
        else:
            print(f"    ✗ 两字段均未解析出: {c['community_id']}")
            # 记录"页面本就无 property_basic/interpretation"(新房项目页/自建房无二手房信息表),
            # 供 loader 排除 → 避免 remaining 永不为 0 导致链式脚本空转
            try:
                _ND = BASE_DIR / "data" / "json_no_data.txt"
                with open(_ND, "a", encoding="utf-8") as _f:
                    _f.write(c["community_id"] + "\n")
            except Exception:
                pass
    return fixed


async def _scrape_surrounding(page, full_text: str = "") -> dict:
    """Extract amenity data by clicking sub-tabs and parsing visible text."""
    categories = ['公交', '地铁', '学校', '餐饮', '购物', '医院', '银行']
    result = {}

    # Click 周边配套 main tab to activate the section
    clicked_main = await page.evaluate("""() => {
        const all = document.querySelectorAll('a, li, span, div, p');
        for (const el of all) {
            if (el.innerText?.trim() === '周边配套' && el.offsetParent !== null) {
                el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                return true;
            }
        }
        return false;
    }""")
    if clicked_main:
        await page.wait_for_timeout(800)

    # Click each sub-category tab and parse the resulting body text
    for cat in categories:
        try:
            clicked = await page.evaluate("""(name) => {
                const all = document.querySelectorAll('a, li, span, div, p');
                for (const el of all) {
                    if (el.innerText?.trim() === name && el.offsetParent !== null) {
                        el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                        return true;
                    }
                }
                return false;
            }""", cat)
            if not clicked:
                continue
            await page.wait_for_timeout(600)

            # Get fresh body text after tab click
            body_text = await page.evaluate("() => document.body?.innerText || ''")
            items = _parse_single_category(body_text, cat, categories)
            if items:
                result[cat] = items
        except Exception:
            pass

    # Fallback: parse from original full_text
    if not result:
        result = _parse_surrounding_from_text(full_text)

    # Map Chinese category names to English keys
    key_map = {'公交': 'bus', '地铁': 'metro', '学校': 'school',
               '餐饮': 'dining', '购物': 'shopping', '医院': 'hospital', '银行': 'bank'}
    return {key_map.get(k, k): v for k, v in result.items()}


def _parse_single_category(text: str, cat_name: str, all_categories: list[str]) -> list[dict]:
    """Parse amenity entries for a single category from body text."""
    items = []
    end_markers = ['小区问答', '小区解读', '小区映像', '房价走势', '本小区热门', '新房推荐']

    # Skip the nav bar "周边配套" and find the section header version.
    # The nav bar line looks like "周边配套小区问答小区解读" — multiple section names jammed together.
    # The actual section header has "周边配套" on its own or followed by a newline.
    amenity_start = -1
    for m in re.finditer(r'周边配套', text):
        pos = m.start()
        before = text[pos - 1:pos] if pos > 0 else '\n'
        after = text[m.end():m.end() + 1] if m.end() < len(text) else ''
        # Section header: preceded by newline or whitespace, followed by newline/whitespace/map
        if before in ('\n', ' ', '\t') and after in ('\n', '\r', '©', ' '):
            amenity_start = pos
            break
    if amenity_start < 0:
        return items

    # End at next major section
    amenity_end = len(text)
    for marker in end_markers:
        idx = text.find(marker, amenity_start + 1)
        if idx > 0 and idx < amenity_end:
            amenity_end = idx
    section = text[amenity_start:amenity_end]

    # Parse name-distance-extra triples
    lines = section.split('\n')
    # Skip ahead past the Baidu map creds + category tab row
    i = 0
    started = False
    while i < len(lines) - 1:
        line = lines[i].strip()
        if not started:
            # Category tab row has e.g. "公交\t地铁\t学校\t餐饮\t购物\t医院\t银行"
            cats_in_line = sum(1 for c in all_categories if c in line)
            if cats_in_line >= 3 or line in all_categories:
                i += 1
                continue
            # Skip Baidu map credits, blank lines
            if any(kw in line for kw in ['Baidu', 'GS(', '京ICP', 'Data ©', '首页新房']):
                i += 1
                continue
            if not line:
                i += 1
                continue
            started = True

        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
        # Entry pattern: Chinese place name followed by distance in meters
        if (re.search(r'[一-鿿]{2,}', line) and
                re.match(r'\d+米', next_line) and
                not any(kw in line for kw in ['首页', '新房', '二手房', '租房', '商铺', '写字楼',
                                                '装修', '楼讯', '房产研究院', '问答', '登录', '注册',
                                                '下载APP', '查看地图', '周边配套'])):
            entry = {"name": line, "distance": next_line}
            # Check for extra info on the following line(s)
            extra_parts = []
            j = i + 2
            while j < len(lines) and j < i + 5:
                extra = lines[j].strip()
                if not extra:
                    break
                if re.match(r'\d+米', extra):
                    break
                if extra in all_categories:
                    break
                if any(kw in extra for kw in end_markers):
                    break
                # If this looks like a new place name (2+ Chinese chars, no route pattern)
                if j > i + 2 and re.search(r'[一-鿿]{2,}', extra) and not re.search(r'[\d路站线;]', extra):
                    break
                extra_parts.append(extra)
                j += 1
            if extra_parts:
                entry["extra"] = '; '.join(extra_parts)
            items.append(entry)
            i = j - 1
        i += 1

    return items[:40]  # Safety cap


def _parse_surrounding_from_text(text: str) -> dict:
    """Parse amenity data from page text (fallback when tab clicking fails)."""
    result = {}
    categories = {
        '公交': 'bus', '地铁': 'metro', '学校': 'school',
        '餐饮': 'dining', '购物': 'shopping', '医院': 'hospital', '银行': 'bank',
    }

    for cn_name, en_name in categories.items():
        items = []
        # Pattern: find the category section and extract name-distance pairs
        # Lines like "潮音大道\\n266米\\n53路; 83路; ..."
        section_start = text.find(cn_name)
        if section_start < 0:
            continue
        section = text[section_start:section_start + 2000]
        lines = section.split('\n')

        # Collect name-distance-route triples
        i = 0
        while i < len(lines) - 1:
            line = lines[i].strip()
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            # Check if line looks like a place name and next line is a distance
            if (re.search(r'[一-鿿]{2,}', line) and
                    re.match(r'\d+米', next_line) and
                    not any(kw in line for kw in categories)):
                entry = {"name": line, "distance": next_line}
                # Check for route info on the following line
                if i + 2 < len(lines) and re.match(r'[\d路站线;\s]+', lines[i + 2].strip()):
                    entry["routes"] = lines[i + 2].strip()
                    i += 1
                items.append(entry)
                i += 1
            i += 1

        if items:
            result[en_name] = items

    return result


def _parse_price_trend(text: str) -> dict | None:
    """Extract price trend data from page text."""
    trend = {}

    # Current price
    price_m = re.search(r'(\d{3,6})\s*元/㎡\s*\n?\s*小区单价', text)
    if price_m:
        trend['current_price'] = int(price_m.group(1))

    # Monthly change
    change_m = re.search(r'比上月\s*\n?\s*([\d.]+)%', text)
    if change_m:
        trend['monthly_change_pct'] = float(change_m.group(1))

    # Shangquan price
    sq_m = re.search(r'(\d{3,6})\s*元/㎡\s*\n?\s*商圈单价', text)
    if sq_m:
        trend['shangquan_price'] = int(sq_m.group(1))

    # Monthly price points (from chart text)
    months = []
    prices = []
    # Pattern: numbers like "7,200元 7,600元 8,000元..." (chart y-axis labels)
    chart_section = text[text.find('房价走势'):text.find('房价走势') + 2000] if '房价走势' in text else ''
    price_nums = re.findall(r'([\d,]+)\s*元', chart_section)
    for pn in price_nums[:13]:
        try:
            prices.append(int(pn.replace(',', '')))
        except ValueError:
            pass

    # Month labels from chart
    month_labels = re.findall(r'(\d{1,2})月', chart_section)
    if month_labels and prices:
        # Pair months with prices (months are usually 12-13 labels)
        for i in range(min(len(month_labels), len(prices))):
            months.append({"month": month_labels[i], "price": prices[i]})
        if months:
            trend['monthly_prices'] = months

    return trend if trend else None


def _parse_reviews(text: str) -> list[dict] | None:
    """Extract agent reviews and community Q&A from page text."""
    reviews = []

    # Agent reviews (小区解读 section)
    # Pattern: name\\ndate\\n【小区优点】...\\n【推荐人群】...
    review_blocks = re.findall(
        r'(.{2,10})\n(\d{4}-\d{2}-\d{2})\n【小区优点】(.+?)(?:【推荐人群】(.+?))?(?:\n|$)',
        text
    )
    for name, date, pros, crowd in review_blocks:
        review = {
            "author": name.strip(),
            "date": date,
            "pros": pros.strip(),
        }
        # Clean up trailing content after crowd section
        if crowd:
            crowd = re.sub(r'(?:本小区|查看更多|房价走势|历年走势|元/㎡).*$', '', crowd).strip()
            review["recommended_for"] = crowd
        reviews.append(review)

    # Community Q&A (小区问答)
    qa_blocks = re.findall(r'【(.+?)】\s*\n?\s*(.+?)\n\s*(\d+)\s*个?回答', text)
    for q_title, q_text, answer_count in qa_blocks[:10]:
        reviews.append({
            "type": "qa",
            "question": q_text.strip() or q_title.strip(),
            "answers": int(answer_count) if answer_count.isdigit() else 0,
        })

    return reviews if reviews else None


def _resolve_city_prov(region_id: str, conn) -> tuple:
    """从 region_id 推出 (city_id, province_id). 杨凌是咸阳的区, 特殊映射."""
    prefix = region_id.split("_")[0] if "_" in region_id else region_id
    city_id = "xianyang" if prefix == "yangling" else prefix
    row = conn.execute("SELECT province_id FROM cities WHERE city_id=?", (city_id,)).fetchone()
    return (city_id, row["province_id"]) if row else (city_id, None)


def save_to_db(communities: list[dict], region_id: str, listings_only: bool = False) -> int:
    create_tables()
    conn = get_db()
    saved = 0
    updated = 0
    # Deterministic per region — compute once. Used as fallback so INSERT OR REPLACE
    # never wipes geo metadata (city_id/province_id) on re-crawl.
    _city_id_default, _prov_id_default = _resolve_city_prov(region_id, conn)
    for c in communities:
        # Preserve original community_id if available, otherwise construct one
        cid = c.get("community_id", "")
        if not cid:
            anjuke_id = c.get("community_id_anjuke", "")
            cid = f"{region_id}_{anjuke_id}" if anjuke_id else f"{region_id}_{slugify(c.get('name',''))}"
        try:
            if listings_only:
                # Non-destructive: existing rows keep their detail fields; we only
                # correct shangquan_id. Brand-new rows are inserted without detail
                # data and picked up later by --details-only.
                existing = conn.execute(
                    "SELECT 1 FROM communities WHERE community_id = ?", (cid,)
                ).fetchone()
                if existing:
                    if c.get("shangquan_id"):
                        conn.execute(
                            "UPDATE communities SET shangquan_id = ?, data_updated = ? WHERE community_id = ?",
                            (c.get("shangquan_id"), now_str(), cid))
                        updated += 1
                else:
                    _city_id, _prov_id = _resolve_city_prov(region_id, conn)
                    conn.execute(
                        """INSERT OR IGNORE INTO communities
                           (community_id, name, address, year_built, developer,
                            property_mgmt, property_fee, floor_area_ratio, green_ratio,
                            parking_ratio, total_units, building_types, unit_sizes,
                            avg_price, listing_count, features,
                            coordinate_lng, coordinate_lat,
                            on_sale_count, on_rent_count, price_trend_json,
                            surrounding_json, community_review, detail_scraped_at,
                            data_source, data_updated, region_id, shangquan_id,
                            property_basic_json, community_interpretation_json, huxingtu_json,
                            city_id, province_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (cid, c.get("name"), c.get("address"), c.get("year_built"),
                         c.get("developer"), c.get("property_mgmt"), c.get("property_fee"),
                         c.get("floor_area_ratio"), c.get("green_ratio"), c.get("parking_ratio"),
                         c.get("total_units"), c.get("building_types"), c.get("unit_sizes"),
                         c.get("avg_price"), c.get("listing_count"), c.get("features"),
                         c.get("coordinate_lng"), c.get("coordinate_lat"),
                         c.get("on_sale_count"), c.get("on_rent_count"), c.get("price_trend_json"),
                         c.get("surrounding_json"), c.get("community_review"), c.get("detail_scraped_at"),
                         "anjuke", now_str(), region_id, c.get("shangquan_id"),
                         c.get("property_basic_json"), c.get("community_interpretation_json"), c.get("huxingtu_json"),
                         _city_id, _prov_id),
                    )
                    saved += 1
            else:
                # INSERT OR REPLACE wipes columns not in the list → preserve geo +
                # shangquan metadata from the existing row, falling back to the
                # region-deterministic defaults. Scrape-provided values win.
                _geo = conn.execute(
                    "SELECT city_id, province_id, district_id, shangquan_id FROM communities WHERE community_id = ?", (cid,)
                ).fetchone()
                _city_id = (_geo["city_id"] if _geo and _geo["city_id"] else _city_id_default)
                _prov_id = (_geo["province_id"] if _geo and _geo["province_id"] else _prov_id_default)
                _district_id = _geo["district_id"] if _geo else None
                _shangquan_id = c.get("shangquan_id") or (_geo["shangquan_id"] if _geo else None)
                conn.execute(
                    """INSERT OR REPLACE INTO communities
                       (community_id, name, address, year_built, developer,
                        property_mgmt, property_fee, floor_area_ratio, green_ratio,
                        parking_ratio, total_units, building_types, unit_sizes,
                        avg_price, listing_count, features,
                        coordinate_lng, coordinate_lat,
                        on_sale_count, on_rent_count, price_trend_json,
                        surrounding_json, community_review, detail_scraped_at,
                        data_source, data_updated, region_id, shangquan_id,
                        property_basic_json, community_interpretation_json, huxingtu_json,
                        city_id, province_id, district_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, c.get("name"), c.get("address"), c.get("year_built"),
                     c.get("developer"), c.get("property_mgmt"), c.get("property_fee"),
                     c.get("floor_area_ratio"), c.get("green_ratio"), c.get("parking_ratio"),
                     c.get("total_units"), c.get("building_types"), c.get("unit_sizes"),
                     c.get("avg_price"), c.get("listing_count"), c.get("features"),
                     c.get("coordinate_lng"), c.get("coordinate_lat"),
                     c.get("on_sale_count"), c.get("on_rent_count"), c.get("price_trend_json"),
                     c.get("surrounding_json"), c.get("community_review"), c.get("detail_scraped_at"),
                     "anjuke", now_str(), region_id, _shangquan_id,
                     c.get("property_basic_json"), c.get("community_interpretation_json"), c.get("huxingtu_json"),
                     _city_id, _prov_id, _district_id),
                )
                saved += 1
        except Exception as e:
            print(f"    DB save error {c.get('name')}: {e}")
    conn.commit()
    conn.close()
    print(f"  Saved {saved} new, updated {updated} (listings-only)" if listings_only else f"  Saved {saved}/{len(communities)}")
    return saved


def load_communities_from_db(region_id: str, missing_only: bool = True,
                             offset: int = 0, limit: int | None = None) -> list[dict]:
    """Load communities from DB for detail re-scraping.

    offset/limit split a region into deterministic disjoint slices for
    dual-machine parallel crawling. ORDER BY community_id is load-bearing:
    community_id is ASCII, so BINARY collation yields byte-identical ordering
    on every machine — required for the slices to line up.
    """
    conn = get_db()
    if missing_only:
        sql = """SELECT community_id, name FROM communities
                 WHERE region_id = ? AND detail_scraped_at IS NULL
                 ORDER BY community_id"""
    else:
        sql = """SELECT community_id, name FROM communities
                 WHERE region_id = ? ORDER BY community_id"""
    params = [region_id]
    if limit is not None and limit > 0:
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    communities = []
    for row in rows:
        cid = row["community_id"]
        name = row["name"]

        # Extract numeric Anjuke ID: try multiple strategies
        # Format examples: "yangling_1034103" or "xianyang_yangling_1034103"
        anjuke_id = ""
        parts = cid.split("_")
        # Take the last part if it's purely numeric
        if parts[-1].isdigit():
            anjuke_id = parts[-1]
        else:
            # Fallback: strip region_id prefix then try
            stripped = cid.replace(f"{region_id}_", "")
            if stripped.isdigit():
                anjuke_id = stripped

        # Determine city slug for Anjuke URL
        # For double-prefix IDs like "xianyang_yangling_1034103", city is parts[0]
        if len(parts) >= 3 and parts[0] not in ("chengdu", "beijing", "shanghai", "guangzhou", "shenzhen"):
            # Could be like "xianyang_yangling_xxx" where xianyang is the real city
            city_slug = parts[0]
        else:
            city_slug = region_id.split("_")[0]

        url = f"https://{city_slug}.anjuke.com/community/view/{anjuke_id}" if anjuke_id.isdigit() else ""

        if not url:
            print(f"    🔍 Will search Anjuke for: {name} (no numeric ID in cid={cid})")

        communities.append({
            "name": name,
            "url": url,
            "city_slug": city_slug,
            "community_id_anjuke": anjuke_id,
            "community_id": cid,  # Preserve original DB primary key
        })
    return communities


def load_communities_missing_names(region_id: str) -> list[dict]:
    """Load communities with empty names (but already detailed) for --fix-names."""
    conn = get_db()
    rows = conn.execute(
        """SELECT community_id FROM communities
           WHERE region_id = ? AND (name IS NULL OR name = '')
           ORDER BY community_id""",
        (region_id,),
    ).fetchall()
    conn.close()

    communities = []
    for row in rows:
        cid = row["community_id"]
        parts = cid.split("_")
        anjuke_id = parts[-1] if parts[-1].isdigit() else ""
        city_slug = region_id.split("_")[0]
        url = f"https://{city_slug}.anjuke.com/community/view/{anjuke_id}" if anjuke_id.isdigit() else ""
        communities.append({
            "name": "",
            "url": url,
            "city_slug": city_slug,
            "community_id_anjuke": anjuke_id,
            "community_id": cid,
        })
    return communities


def load_communities_missing_json(region_id: str) -> list[dict]:
    """Load communities with detail but missing property_basic (08-11 前旧代码爬的) → --fix-json。

    重访详情页补 property_basic_json + community_interpretation_json。
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT community_id FROM communities
           WHERE region_id = ? AND detail_scraped_at IS NOT NULL
             AND (property_basic_json IS NULL OR property_basic_json = '')
           ORDER BY community_id""",
        (region_id,),
    ).fetchall()
    conn.close()

    # 排除已知"页面本无数据"的社区(新房项目页/自建房), 否则 remaining 永不归零
    no_data = set()
    try:
        _ND = BASE_DIR / "data" / "json_no_data.txt"
        if _ND.exists():
            no_data = {ln.strip() for ln in _ND.read_text(encoding="utf-8").splitlines() if ln.strip()}
    except Exception:
        pass

    communities = []
    for row in rows:
        cid = row["community_id"]
        if cid in no_data:
            continue
        parts = cid.split("_")
        anjuke_id = parts[-1] if parts[-1].isdigit() else ""
        city_slug = region_id.split("_")[0]
        url = f"https://{city_slug}.anjuke.com/community/view/{anjuke_id}" if anjuke_id.isdigit() else ""
        communities.append({
            "name": "",
            "url": url,
            "city_slug": city_slug,
            "community_id_anjuke": anjuke_id,
            "community_id": cid,
        })
    return communities


async def main():
    global _ACTIVE_STATE_FILE
    create_tables()
    max_communities = 0
    show_browser = False
    xvfb_mode = False        # --xvfb: non-headless but no human captcha wait
    login_mode = False
    manual_mode = False
    details_only = False
    listings_only = False
    fix_names = False
    fix_json = False
    use_system_chrome = False
    profile_dir = None        # --profile: persistent Chrome profile (CubeMini)
    region_id = DEFAULT_REGION
    shangquan = None
    offset = 0
    limit = None           # None = no LIMIT (all rows); --limit N > 0 slices

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--max" and i + 1 < len(args):
            max_communities = int(args[i + 1]); i += 2
        elif args[i] == "--offset" and i + 1 < len(args):
            offset = int(args[i + 1]); i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif args[i] == "--region" and i + 1 < len(args):
            region_id = args[i + 1]; i += 2
        elif args[i] == "--shangquan" and i + 1 < len(args):
            shangquan = args[i + 1]; i += 2
        elif args[i] == "--show":
            show_browser = True; i += 1
        elif args[i] == "--xvfb":
            xvfb_mode = True; i += 1
        elif args[i] == "--login":
            login_mode = True; i += 1
        elif args[i] == "--manual":
            manual_mode = True; i += 1
        elif args[i] == "--details-only":
            details_only = True; i += 1
        elif args[i] == "--listings-only":
            listings_only = True; i += 1
        elif args[i] == "--fix-names":
            fix_names = True; i += 1
        elif args[i] == "--fix-json":
            fix_json = True; i += 1
        elif args[i] == "--chrome":
            use_system_chrome = True; i += 1
        elif args[i] == "--profile" and i + 1 < len(args):
            profile_dir = args[i + 1]; i += 2
        elif args[i] == "--proxy" and i + 1 < len(args):
            _PROXY_SERVER = args[i + 1]; i += 2
        elif args[i] == "--state" and i + 1 < len(args):
            _ACTIVE_STATE_FILE = Path(args[i + 1]); i += 2
        else:
            i += 1

    # --offset/--limit validation (dual-machine slice support)
    if offset < 0:
        offset = 0
    if limit is not None and limit <= 0:
        print("Error: --limit must be a positive integer (omit --limit for all rows)")
        return

    region = get_region(region_id)
    anjuke_url = region["anjuke_url"]
    city_slug = region_id.split("_")[0] if "_" in region_id else region_id

    # Set up per-city state file (unless explicitly overridden by --state flag)
    if _ACTIVE_STATE_FILE == _LEGACY_STATE_FILE and city_slug:
        _ACTIVE_STATE_FILE = _resolve_state_for_city(city_slug)
    print(f"  State file: {_ACTIVE_STATE_FILE}")
    if shangquan and shangquan != "all":
        # Load shangquan URL from saved JSON
        sq_file = BASE_DIR / "data" / f"shangquan_{city_slug}.json"
        # Fallback: search all shangquan_*.json files for matching city field
        if not sq_file.exists():
            for candidate in (BASE_DIR / "data").glob("shangquan_*.json"):
                try:
                    cdata = json.loads(candidate.read_text())
                    if cdata.get("city") == city_slug:
                        sq_file = candidate
                        break
                except Exception:
                    pass
        if sq_file.exists():
            sq_data = json.loads(sq_file.read_text())
            for dist_name, dist_info in sq_data.get("districts", {}).items():
                for sq in dist_info.get("shangquan", []):
                    if sq["name"] == shangquan:
                        anjuke_url = sq["url"]
                        print(f"  Shangquan filter: {shangquan} → {anjuke_url}")
                        break
                else:
                    continue
                break
            else:
                print(f"  Warning: 商圈 '{shangquan}' not found in {sq_file.name}, using district URL")

    # Batch mode: scrape all shangquan
    batch_shangquan = (shangquan == "all")

    if login_mode:
        ok = await login_and_save_cookies(anjuke_url, headless=not (show_browser or xvfb_mode), manual=manual_mode)
        if not ok:
            print("Auto-login failed. Exiting.")
        return

    # Per-profile mode: session is self-contained in the Chrome profile directory.
    # Skip the state-file check — the browser will load cookies directly from the profile.
    cookies = load_cookies() if not profile_dir else []
    if not profile_dir and (not cookies or not get_state_file().exists()):
        print("No saved state — running auto-login first...")
        ok = await login_and_save_cookies(anjuke_url, headless=not (show_browser or xvfb_mode), manual=manual_mode)
        if not ok:
            print("Auto-login failed. Exiting.")
            return
        cookies = load_cookies()
        if not cookies:
            print("Still no cookies after auto-login. Exiting.")
            return

    if details_only:
        communities = load_communities_from_db(region_id, missing_only=True,
                                               offset=offset, limit=limit)
        print(f"Details-only mode — {len(communities)} communities missing detail data")
        if not communities:
            print("All communities have detail data. Nothing to do.")
            return
        if max_communities > 0 and len(communities) > max_communities:
            communities = communities[:max_communities]
            print(f"  Limited to {max_communities} by --max")
    else:
        communities = None  # Will be populated from listing

    print(f"Anjuke Scraper — {region['name']} ({region['city']})  |  max: {max_communities or 'all'}")
    print(f"  URL: {anjuke_url}")
    print(f"  Cookies: {len(cookies)}")

    CHROME_PROFILE_DIR = BASE_DIR / "chrome_profile_v2"

    async with async_playwright() as p:
        if profile_dir:
            # Persistent Chrome profile — maintains browser fingerprint across sessions
            # This is what worked on CubeMini for 28,586 communities
            import subprocess as _sp
            _sp.run(["pkill", "-f", "chrome_profile"], capture_output=True)
            import time as _time; _time.sleep(2)
            _prof = Path(profile_dir)
            _lock = _prof / "SingletonLock"
            if _lock.exists():
                try:
                    _lock.unlink()
                except Exception:
                    pass
            print(f"  Using persistent profile: {_prof}")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(_prof),
                headless=not (show_browser or xvfb_mode),
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                args=_browser_launch_args(),
            )
            page = context.pages[0] if context.pages else await context.new_page()
        elif use_system_chrome:
            # Kill any lingering Chrome using our profile
            import subprocess as _sp
            _sp.run(["pkill", "-f", "chrome_profile"], capture_output=True)
            import time as _time; _time.sleep(2)
            _lock = CHROME_PROFILE_DIR / "SingletonLock"
            if _lock.exists():
                try:
                    _lock.unlink()
                except Exception:
                    pass
            # Use launch + persistent storage state — more reliable than launch_persistent_context
            browser = await p.chromium.launch(
                channel='chrome',
                headless=False,
                args=_browser_launch_args(),
            )
            # Load persistent state if exists
            _state_file = CHROME_PROFILE_DIR / "state.json"
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                storage_state=str(_state_file) if _state_file.exists() else None,
            )
        else:
            browser = await p.chromium.launch(
                headless=not (show_browser or xvfb_mode),
                args=_browser_launch_args(),
            )
            context = await browser.new_context(
                user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
                storage_state=str(get_state_file()) if get_state_file().exists() else None,
            )
            if not get_state_file().exists() and cookies:
                await context.add_cookies(cookies)
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)

        async def _close():
            if use_system_chrome:
                # Save state to persist cookies
                _state_file = CHROME_PROFILE_DIR / "state.json"
                try:
                    _state = await context.storage_state()
                    _state_file.write_text(json.dumps(_state))
                except Exception:
                    pass
            await browser.close()

        async def _relaunch():
            nonlocal browser, context, page
            try:
                await _close()
            except Exception:
                pass
            if use_system_chrome:
                import subprocess as _sp
                _sp.run(["pkill", "-f", "chrome_profile"], capture_output=True)
                import time as _time; _time.sleep(2)
                _lock = CHROME_PROFILE_DIR / "SingletonLock"
                if _lock.exists():
                    try:
                        _lock.unlink()
                    except Exception:
                        pass
                browser = await p.chromium.launch(
                    channel='chrome',
                    headless=False,
                    args=_browser_launch_args(),
                )
                _state_file = CHROME_PROFILE_DIR / "state.json"
                context = await browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    storage_state=str(_state_file) if _state_file.exists() else None,
                )
            else:
                browser = await p.chromium.launch(
                    headless=not (show_browser or xvfb_mode),
                    args=_browser_launch_args(),
                )
                context = await browser.new_context(
                    user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
                    storage_state=str(get_state_file()) if get_state_file().exists() else None,
                )
            page = await context.new_page()
            await page.add_init_script(STEALTH_JS)

        if fix_names:
            communities = load_communities_missing_names(region_id)
            print(f"\nFix-names mode — {len(communities)} communities with empty names")
            if not communities:
                print("Nothing to do.")
            else:
                fixed = await scrape_names(page, communities, show_browser=show_browser)
                print(f"  Fixed {fixed}/{len(communities)} names")
            await _close()
            return

        if fix_json:
            communities = load_communities_missing_json(region_id)
            if max_communities > 0:
                communities = communities[:max_communities]
            print(f"\nFix-json mode — {len(communities)} communities missing property_basic/interpretation")
            if not communities:
                print("Nothing to do.")
            else:
                fixed = await scrape_json(page, communities, show_browser=show_browser)
                print(f"  Fixed {fixed}/{len(communities)} json fields")
            await _close()
            return

        if batch_shangquan:
            # Extract district slug from region_id (e.g. beijing_xicheng → xicheng).
            # 整市 region (无下划线, 如 shenzhen/shanghai/guangzhou) → 不按区过滤, 处理全部区
            district_slug = region_id.split("_", 1)[1] if "_" in region_id else ""
            district_display_name = region.get("name", "")  # Chinese display name
            await scrape_all_shangquan(page, region_id, city_slug, district_slug, max_communities, show_browser=show_browser, district_display_name=district_display_name, listings_only=listings_only)
            await _close()
            return

        if not details_only:
            print("\n[1/2] Scraping listing...")
            communities = await scrape_listing(page, anjuke_url, max_communities, show_browser=show_browser)
            print(f"  Found {len(communities)} communities")

            if not communities:
                await _close()
                return

            if listings_only:
                print(f"\n  [listings-only] Saving {len(communities)} and exiting...")
                saved = save_to_db(communities, region_id)
                print(f"  Saved {saved}/{len(communities)} communities (no details)")
                await _close()
                return

        print(f"\n[2/2] Scraping detail pages ({len(communities)} communities)...")
        i = 0
        while i < len(communities):
            c = communities[i]
            print(f"\n  [{i+1}/{len(communities)}] {c['name']}")
            try:
                communities[i] = await scrape_detail(page, c, show_browser=show_browser)
                delay_s = random.uniform(DETAIL_DELAY_MIN_MS, DETAIL_DELAY_MAX_MS) / 1000
                print(f"    Waiting {delay_s:.0f}s...")
                await page.wait_for_timeout(int(delay_s * 1000))
                i += 1
            except Exception as e:
                print(f"    Browser/page error: {e}")
                print(f"    Re-launching browser and retrying...")
                await _relaunch()
                if not get_state_file().exists():
                    await context.add_cookies(load_cookies())
                page = await context.new_page()
                await page.add_init_script(STEALTH_JS)
                await page.wait_for_timeout(2000)

            # Save incrementally every 10 communities
            if (i > 0 and i % 10 == 0) or i == len(communities) - 1:
                save_to_db(communities[:i + (1 if i == len(communities) - 1 else 0)], region_id)
                print(f"    [Saved {min(i+1, len(communities))}/{len(communities)}]")

        if use_system_chrome:
            _state_file = CHROME_PROFILE_DIR / "state.json"
            try:
                _state = await context.storage_state()
                _state_file.write_text(json.dumps(_state))
            except Exception:
                pass
        else:
            save_cookies(await context.cookies())
        await _close()

    print(f"\nFinal save to DB (region: {region_id})...")
    saved = save_to_db(communities, region_id)
    print(f"Done. {saved}/{len(communities)} saved.")


if __name__ == "__main__":
    asyncio.run(main())
