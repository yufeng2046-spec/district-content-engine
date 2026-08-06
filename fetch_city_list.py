#!/usr/bin/env python3
"""一次性抓取安居客权威省市列表 (sy-city.html)。

可见 Chrome 打开 sy-city.html, 等人工过验证码 (最多 10 分钟),
通过后抓取完整页面 HTML 和文本, 供解析省市结构。
"""
import asyncio
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from playwright.async_api import async_playwright
from config import USER_AGENT
from data.scrapers.stealth import STEALTH_JS

URL = "https://www.anjuke.com/sy-city.html"
STATE = BASE_DIR / "anjuke_state.json"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
            storage_state=str(STATE) if STATE.exists() else None,
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_JS)
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)

        print("=" * 55)
        print("请在 Chrome 窗口中完成验证码（如出现）")
        print("完成后脚本自动检测并继续，无需按任何键")
        print("=" * 55, flush=True)

        # 轮询直到验证码清除且 URL 回到 sy-city (连续 2 次稳定判定)
        cleared = False
        stable = 0
        for _ in range(120):  # 120 * 5s = 最多 10 分钟
            await page.wait_for_timeout(5000)
            try:
                url = page.url
                title = await page.title()
            except Exception:
                continue
            is_captcha = (
                "captcha" in url.lower()
                or "antibot" in url.lower()
                or "verify" in url.lower()
                or "验证" in title
            )
            on_city_page = "sy-city" in url
            if not is_captcha and on_city_page:
                stable += 1
                if stable >= 2:
                    cleared = True
                    print("✅ 验证码已清除，正在等待城市列表渲染...", flush=True)
                    break
            else:
                stable = 0

        if not cleared:
            print("❌ 10 分钟内未通过验证码，退出", flush=True)
            await browser.close()
            return

        # 等 Vue 组件把城市列表渲染出来
        await page.wait_for_timeout(6000)
        html = await page.content()
        Path("/tmp/sycity_raw.html").write_text(html, encoding="utf-8")
        text = await page.evaluate("() => document.body.innerText")
        Path("/tmp/sycity_text.txt").write_text(text, encoding="utf-8")
        print(f"✅ 已保存: /tmp/sycity_raw.html ({len(html)} bytes)", flush=True)
        print(f"✅ 已保存: /tmp/sycity_text.txt ({len(text)} chars)", flush=True)
        print("完成", flush=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
