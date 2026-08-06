#!/usr/bin/env python3
"""独立户型爬取 — 抓每个小区的 huxingtu 页, 存 huxingtu_json。

用法:
    python3 scrape_huxingtu.py                 # 全部缺户型的
    python3 scrape_huxingtu.py --region xa     # 只爬某城市
    python3 scrape_huxingtu.py --limit 10      # 测试: 只爬 10 个
    python3 scrape_huxingtu.py --show          # 可见 Chrome, 可人工过验证码
    python3 scrape_huxingtu.py --xvfb          # 非 headless, 验证码自动跳过

每小区 1 次请求 (https://{city}.anjuke.com/community/huxingtu/{anjuke_id}/)。
断点续跑: 已存 huxingtu_json 的小区自动跳过。无户型的存 '[]' 以免重复爬。
"""
from __future__ import annotations  # Python 3.9: 延迟求值类型注解 (str | None)

import asyncio
import json
import random
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from playwright.async_api import async_playwright
from config import USER_AGENT
from data.scrapers.stealth import STEALTH_JS
from db.connection import get_db

LEGACY_STATE = BASE_DIR / "anjuke_state.json"

# 城市子域 → state 文件 (与主爬虫一致)
def _resolve_state(city_id: str) -> Path:
    pc = BASE_DIR / f"anjuke_state_{city_id}.json"
    if pc.exists():
        return pc
    return LEGACY_STATE


def _parse_huxingtu(html: str) -> list[dict]:
    """从 huxingtu 页 HTML 提取户型列表: [{type, rooms, halls, area, image}]"""
    results = []
    blocks = html.split('<div class="huxing-detail"')[1:]
    for b in blocks:
        desc = re.search(r"huxing-desc[^>]*>\s*([^<]+)<", b)
        img = re.search(r'data-src="([^"]+)"', b)
        if not desc:
            continue
        m = re.match(r"(\d+)室(\d+)厅\s+([\d.]+)平米", desc.group(1).strip())
        if not m:
            continue
        results.append({
            "type": f"{m.group(1)}室{m.group(2)}厅",
            "rooms": int(m.group(1)),
            "halls": int(m.group(2)),
            "area": float(m.group(3)),
            "image": img.group(1) if img else None,
        })
    return results


async def process_community(page, conn, city_id: str, community_id: str, anjuke_id: str,
                            expected_name: str, show_browser: bool) -> str | None:
    """抓一个小区户型页, 返回 huxingtu_json 字符串; None=失败/跳过."""
    url = f"https://{city_id}.anjuke.com/community/huxingtu/{anjuke_id}/"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except Exception:
        return None
    await asyncio.sleep(random.uniform(1.0, 2.0))
    try:
        title = await page.title()
    except Exception:
        return None

    # 验证码: headless 跳过, --show 等人工
    if "验证" in title:
        if show_browser:
            print(f"    🔐 验证码, 请人工处理...")
            for _ in range(60):  # 最多 5 分钟
                await asyncio.sleep(5)
                try:
                    title = await page.title()
                    if "验证" not in title:
                        break
                except Exception:
                    pass
        else:
            print(f"    🔒 验证码, 跳过")
            return None

    html = await page.content()

    # ── 防错闸: 校验页面属于数据库里的这个小区 ──
    # 页面面包屑/标题/正文应包含小区名; 对不上说明 anjuke 返回了错页, 跳过不存
    try:
        page_text = await page.evaluate("() => document.body.innerText")
        if expected_name and expected_name not in page_text:
            print(f"    ⚠️ 页面小区名不匹配 (期望 {expected_name}), 跳过")
            return None
    except Exception:
        pass  # 校验失败不阻断, 交给 huxing-detail 判断

    if "huxing-detail" not in html:
        return "[]"  # 无户型 (存空数组, 标记已完成)
    plans = _parse_huxingtu(html)
    if not plans:
        return "[]"
    return json.dumps(plans, ensure_ascii=False)


async def main():
    show_browser = "--show" in sys.argv
    xvfb = "--xvfb" in sys.argv
    region_filter = None
    limit = 0
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--region" and i + 1 < len(args):
            region_filter = args[i + 1]
        if a == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])

    conn = get_db()
    # 待爬小区: 无 huxingtu_json 的, 按城市分组 (利于 state 复用)
    # anjuke_id 嵌在 community_id 末尾 (最后一个 _ 之后), 无独立列
    sql = """SELECT c.community_id, c.city_id, c.name
             FROM communities c WHERE c.huxingtu_json IS NULL"""
    params = []
    if region_filter:
        sql += " AND c.city_id = ?"
        params.append(region_filter)
    sql += " ORDER BY c.city_id, c.community_id"
    if limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    targets = conn.execute(sql, params).fetchall()
    conn.close()
    print(f"待爬小区: {len(targets)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not (show_browser or xvfb),
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        current_state = None
        page = None
        ok = 0
        empty = 0
        failed = 0
        for i, t in enumerate(targets):
            community_id = t["community_id"]
            city_id = t["city_id"]
            expected_name = t["name"]
            anjuke_id = community_id.rsplit("_", 1)[-1]
            if not anjuke_id or not anjuke_id.isdigit():
                continue
            # 每个城市切换 state (复用主爬虫的 per-city state)
            want_state = _resolve_state(city_id)
            if current_state != want_state:
                if page:
                    await page.context.close()
                context = await browser.new_context(
                    user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
                    storage_state=str(want_state) if want_state.exists() else None,
                )
                page = await context.new_page()
                await page.add_init_script(STEALTH_JS)
                current_state = want_state

            print(f"[{i+1}/{len(targets)}] {community_id}", flush=True)
            try:
                result = await process_community(page, conn, city_id, community_id, anjuke_id, expected_name, show_browser)
            except Exception as e:
                print(f"    ❌ {e}")
                result = None
            if result is not None:
                conn = get_db()
                conn.execute("UPDATE communities SET huxingtu_json=? WHERE community_id=?",
                             (result, community_id))
                conn.commit()
                conn.close()
                if result == "[]":
                    empty += 1
                else:
                    ok += 1
                    n = len(json.loads(result))
                    print(f"    ✅ {n} 个户型")
            else:
                failed += 1

            # 节奏: 每 15 个小区慢一点 (风控)
            delay = random.uniform(2.0, 4.0)
            if (i + 1) % 15 == 0:
                delay = random.uniform(6.0, 10.0)
            await asyncio.sleep(delay)

        await browser.close()

    print(f"\n完成: 有户型 {ok} | 无户型 {empty} | 失败 {failed}")


if __name__ == "__main__":
    asyncio.run(main())
