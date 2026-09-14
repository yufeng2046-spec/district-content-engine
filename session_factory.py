#!/usr/bin/env python3
"""
Session Factory — create per-city Anjuke browser sessions for dual-IP scraping.

Opens ONE visible Chrome window. Iterates through configured cities,
navigates to each city's Anjuke homepage, and waits for you to solve
the captcha (if any). Saves per-city browser state files that CubeMini
can then use for headless scraping.

Usage:
    python3 session_factory.py                    # All configured cities
    python3 session_factory.py --cities beijing,shanghai   # Specific cities
    python3 session_factory.py --show-sessions     # Show session status only

Output:
    anjuke_state_{city}.json  — Playwright storage_state for each city
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from playwright.async_api import async_playwright
from config import USER_AGENT
from data.scrapers.stealth import STEALTH_JS

# ═══ City Configuration ═══
# Cities to create sessions for, in priority order
# Format: (city_slug, city_name, anjuke_homepage)
CITIES = [
    ("beijing",     "北京",     "https://beijing.anjuke.com/"),
    ("shanghai",    "上海",     "https://shanghai.anjuke.com/"),
    ("guangzhou",   "广州",     "https://guangzhou.anjuke.com/"),
    ("shenzhen",    "深圳",     "https://shenzhen.anjuke.com/"),
    ("chengdu",     "成都",     "https://chengdu.anjuke.com/"),
    ("xa",          "西安",     "https://xa.anjuke.com/"),
    ("hangzhou",    "杭州",     "https://hangzhou.anjuke.com/"),
    ("nanjing",     "南京",     "https://nanjing.anjuke.com/"),
    ("wuhan",       "武汉",     "https://wuhan.anjuke.com/"),
    ("tianjin",     "天津",     "https://tianjin.anjuke.com/"),
    ("chongqing",   "重庆",     "https://chongqing.anjuke.com/"),
    ("suzhou",      "苏州",     "https://suzhou.anjuke.com/"),
    ("changsha",    "长沙",     "https://changsha.anjuke.com/"),
    ("zhengzhou",   "郑州",     "https://zhengzhou.anjuke.com/"),
    ("dongguan",    "东莞",     "https://dongguan.anjuke.com/"),
    ("qingdao",     "青岛",     "https://qingdao.anjuke.com/"),
    ("hefei",       "合肥",     "https://hefei.anjuke.com/"),
    ("foshan",      "佛山",     "https://foshan.anjuke.com/"),
    ("dalian",      "大连",     "https://dalian.anjuke.com/"),
    ("jinan",       "济南",     "https://jinan.anjuke.com/"),
    ("kunming",     "昆明",     "https://kunming.anjuke.com/"),
    ("xiamen",      "厦门",     "https://xiamen.anjuke.com/"),
    ("fuzhou",      "福州",     "https://fuzhou.anjuke.com/"),
    ("nanning",     "南宁",     "https://nanning.anjuke.com/"),
    ("guiyang",     "贵阳",     "https://guiyang.anjuke.com/"),
    ("wuxi",        "无锡",     "https://wuxi.anjuke.com/"),
    ("ningbo",      "宁波",     "https://ningbo.anjuke.com/"),
    ("langfang",    "廊坊",     "https://langfang.anjuke.com/"),
    ("datong",      "大同",     "https://datong.anjuke.com/"),
    ("yangling",    "杨凌",     "https://xianyang.anjuke.com/community/yangling/"),
]


def state_path(city: str) -> Path:
    return BASE_DIR / f"anjuke_state_{city}.json"


def show_sessions():
    """Show status of all per-city state files."""
    print("\n📊 Per-City Session Status:\n")
    print(f"{'City':<12} {'State File':<32} {'Age':<10} {'Status'}")
    print("-" * 70)
    fresh_count = 0
    stale_count = 0
    missing_count = 0

    for city_slug, city_name, _ in CITIES:
        sp = state_path(city_slug)
        if sp.exists():
            age_seconds = time.time() - sp.stat().st_mtime
            if age_seconds < 3600:
                age_str = f"{age_seconds/60:.0f}min"
                status = "✅ fresh"
                fresh_count += 1
            elif age_seconds < 86400:
                age_str = f"{age_seconds/3600:.1f}h"
                status = "⚠️  stale"
                stale_count += 1
            else:
                age_str = f"{age_seconds/86400:.1f}d"
                status = "❌ old"
                stale_count += 1
            size_kb = sp.stat().st_size / 1024
            print(f"{city_name:<12} {sp.name:<32} {age_str:<10} {status} ({size_kb:.0f}KB)")
        else:
            print(f"{city_name:<12} {'(not created)':<32} {'—':<10} ⬜ missing")
            missing_count += 1

    print(f"\n  {fresh_count} fresh, {stale_count} stale/old, {missing_count} missing")
    legacy = BASE_DIR / "anjuke_state.json"
    if legacy.exists():
        age_h = (time.time() - legacy.stat().st_mtime) / 3600
        print(f"  Legacy anjuke_state.json: {age_h:.1f}h old ({legacy.stat().st_size/1024:.0f}KB)")


async def create_sessions(city_filter: list = None):
    """Open visible Chrome, create per-city sessions one by one."""
    cities_to_process = [
        (slug, name, url)
        for slug, name, url in CITIES
        if city_filter is None or slug in city_filter
    ]

    if not cities_to_process:
        print("No cities to process.")
        return

    print("\n🔑 Session Factory — Creating Per-City Anjuke Sessions\n")
    print(f"  Cities: {len(cities_to_process)}")
    print(f"  Browser: Visible Chrome (solve captchas manually)")
    print(f"  Output:  anjuke_state_{{city}}.json\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        for idx, (city_slug, city_name, url) in enumerate(cities_to_process):
            sp = state_path(city_slug)
            print(f"\n{'─' * 50}")
            print(f"[{idx+1}/{len(cities_to_process)}] {city_name} ({city_slug})")
            print(f"  URL: {url}")

            # Check if we already have a fresh session
            if sp.exists():
                age_min = (time.time() - sp.stat().st_mtime) / 60
                if age_min < 60:
                    print(f"  ⏭️  Session is {age_min:.0f}min old — skipping (still fresh)")
                    continue
                else:
                    print(f"  ⚠️  Existing session is {age_min:.0f}min old — refreshing")

            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
            page = await context.new_page()
            await page.add_init_script(STEALTH_JS)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                await page.goto(url, wait_until="commit", timeout=30000)

            await page.wait_for_timeout(2000)

            title = await page.title()
            has_captcha = "验证" in title or "captcha" in title.lower()

            if has_captcha:
                print(f"  🔒 Captcha detected!")
                print(f"  ╔══════════════════════════════════════════════╗")
                print(f"  ║  👆 请在 Chrome 窗口中完成 {city_name} 的验证码     ║")
                print(f"  ║  完成后回到终端按 Enter 继续...              ║")
                print(f"  ╚══════════════════════════════════════════════╝")
                input()
            else:
                print(f"  ✅ No captcha — page loaded clean")

            # Save per-city state
            try:
                state = await page.context.storage_state()
                sp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
                size_kb = sp.stat().st_size / 1024
                print(f"  💾 Saved: {sp.name} ({size_kb:.0f}KB)")
            except Exception as e:
                print(f"  ❌ Failed to save state: {e}")

            await context.close()

        await browser.close()

    print(f"\n{'═' * 50}")
    print("✅ Session factory complete!")
    show_sessions()
    print("\n💡 Next: python3 sync_state_to_cubemini.py  (sync to CubeMini)")


async def main():
    args = sys.argv[1:]
    city_filter = None

    if "--show-sessions" in args:
        show_sessions()
        return

    i = 0
    while i < len(args):
        if args[i] == "--cities" and i + 1 < len(args):
            city_filter = [c.strip() for c in args[i + 1].split(",")]
            i += 2
        else:
            i += 1

    await create_sessions(city_filter)


if __name__ == "__main__":
    asyncio.run(main())
