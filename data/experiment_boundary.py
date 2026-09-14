"""
First-principles exploration of Anjuke anti-bot boundaries.

Tests: rate limit, session duration, volume cap, stealth effectiveness, recovery.
"""

import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright
from config import USER_AGENT
from data.scrapers.stealth import STEALTH_JS

STATE_FILE = Path(__file__).resolve().parent.parent / "anjuke_state.json"
TEST_URL = "https://chengdu.anjuke.com/community/view/1598245/"  # Known working detail page


async def check_captcha(page) -> bool:
    """Return True if captcha is present."""
    try:
        title = await page.title()
        return "验证" in title
    except Exception:
        return True


async def test_single_request(context) -> dict:
    """Make one request, return timing and result."""
    page = await context.new_page()
    await page.add_init_script(STEALTH_JS)
    t0 = time.time()
    try:
        await page.goto(TEST_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1000)
        blocked = await check_captcha(page)
        elapsed = time.time() - t0
        return {"blocked": blocked, "elapsed": round(elapsed, 2)}
    except Exception as e:
        return {"blocked": True, "elapsed": round(time.time() - t0, 2), "error": str(e)[:60]}
    finally:
        await page.close()


# ── Experiment 1: Rate Limit Threshold ────────────────────
async def exp1_rate_limit():
    """Test: at what request-per-minute rate does captcha appear?"""
    print("\n" + "=" * 60)
    print("Experiment 1: Rate Limit Threshold")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        for rpm, delay_s in [(3, 20.0), (6, 10.0), (10, 6.0), (15, 4.0), (20, 3.0)]:
            # Fresh context for each RPM test
            context = await browser.new_context(
                user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
                storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
            )
            results = []
            blocked_at = None

            for i in range(20):  # 20 requests per RPM level
                r = await test_single_request(context)
                results.append(r)
                if r["blocked"] and blocked_at is None:
                    blocked_at = i + 1
                if r["blocked"]:
                    break  # Stop once blocked
                await asyncio.sleep(delay_s)

            blocked_count = sum(1 for r in results if r["blocked"])
            avg_elapsed = sum(r["elapsed"] for r in results) / len(results) if results else 0
            print(f"  RPM~{rpm} ({delay_s}s delay): {len(results)} requests, "
                  f"blocked at #{blocked_at or 'never'}, avg {avg_elapsed:.1f}s, "
                  f"{blocked_count} total blocked")
            await context.close()

            if blocked_at and blocked_at <= 3:
                print(f"  → Threshold found: RPM > {rpm} triggers immediate block")
                break

        await browser.close()


# ── Experiment 2: Session Duration ────────────────────────
async def exp2_session_duration():
    """Test: how long does a session last with moderate (6 RPM) rate?"""
    print("\n" + "=" * 60)
    print("Experiment 2: Session Duration (6 RPM)")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
        )

        t_start = time.time()
        request_count = 0
        blocked_count = 0
        blocked_at = None

        for minute in range(30):  # Test up to 30 minutes
            for _ in range(6):  # 6 requests per minute
                r = await test_single_request(context)
                request_count += 1
                if r["blocked"]:
                    blocked_count += 1
                    if blocked_at is None:
                        blocked_at = request_count
                        elapsed_min = (time.time() - t_start) / 60
                        print(f"  First block at req #{blocked_at} ({elapsed_min:.1f} min)")
                await asyncio.sleep(8)  # ~7.5 RPM

            elapsed_min = (time.time() - t_start) / 60
            if blocked_count > request_count * 0.5:  # >50% blocked
                print(f"  Session degraded: {request_count} reqs, {blocked_count} blocked "
                      f"after {elapsed_min:.1f} min")
                break

            if minute % 5 == 4:
                print(f"  {elapsed_min:.0f} min: {request_count} reqs, {blocked_count} blocked")

        await context.close()
        await browser.close()

    elapsed = (time.time() - t_start) / 60
    print(f"  Total: {request_count} requests over {elapsed:.1f} min, "
          f"{blocked_count} blocked ({100*blocked_count//max(request_count,1)}%)")


# ── Experiment 3: Recovery After Block ────────────────────
async def exp3_recovery():
    """Test: after getting blocked, how long to wait before a fresh session works?"""
    print("\n" + "=" * 60)
    print("Experiment 3: Recovery Time")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        # First: trigger a block (rapid requests)
        print("  Phase A: Trigger block with rapid requests...")
        context = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
        )
        for i in range(10):
            r = await test_single_request(context)
            if r["blocked"]:
                print(f"  Blocked at request #{i+1}")
                break
            await asyncio.sleep(0.5)
        await context.close()

        # Test recovery at intervals
        for wait_s in [30, 60, 120, 300]:
            print(f"  Waiting {wait_s}s...")
            await asyncio.sleep(wait_s)

            context2 = await browser.new_context(
                user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
            )
            r = await test_single_request(context2)
            print(f"  After {wait_s}s: {'BLOCKED' if r['blocked'] else 'OK'}")
            await context2.close()

            if not r["blocked"]:
                print(f"  → Recovery time: {wait_s}s")
                break

        await browser.close()


# ── Experiment 4: Stealth JS Effectiveness ────────────────
async def exp4_stealth():
    """Test: does stealth JS actually help avoid detection?"""
    print("\n" + "=" * 60)
    print("Experiment 4: Stealth JS vs No Stealth")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        for label, use_stealth in [("WITH stealth", True), ("NO stealth", False)]:
            context = await browser.new_context(
                user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
            )
            page = await context.new_page()
            if use_stealth:
                await page.add_init_script(STEALTH_JS)

            blocked_at = None
            for i in range(10):
                try:
                    await page.goto(TEST_URL, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(500)
                    if await check_captcha(page):
                        if blocked_at is None:
                            blocked_at = i + 1
                        break
                except Exception:
                    if blocked_at is None:
                        blocked_at = i + 1
                    break
                await asyncio.sleep(1.0)

            print(f"  {label}: {'blocked at #' + str(blocked_at) if blocked_at else 'all 10 OK'}")
            await context.close()

        await browser.close()


# ── Experiment 5: Cookie persistence across subdomains ────
async def exp5_cookie_domain():
    """Test: do .anjuke.com cookies work across subdomains?"""
    print("\n" + "=" * 60)
    print("Experiment 5: Cookie Cross-Domain")
    print("=" * 60)

    if not STATE_FILE.exists():
        print("  No state file — skipping (need manual login first)")
        return

    state = json.loads(STATE_FILE.read_text())
    cookies = state.get("cookies", [])
    anjuke_cookies = [c for c in cookies if "anjuke" in c.get("domain", "")]
    print(f"  {len(anjuke_cookies)} anjuke cookies loaded")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        for url, label in [
            ("https://chengdu.anjuke.com/community/view/1598245/", "chengdu"),
            ("https://xa.anjuke.com/community/view/1443091/", "xian"),
            ("https://yangling.anjuke.com/community/view/12345/", "yangling"),
            ("https://beijing.anjuke.com/community/view/12345/", "beijing"),
        ]:
            context = await browser.new_context(
                user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="zh-CN",
                storage_state=str(STATE_FILE),
            )
            page = await context.new_page()
            await page.add_init_script(STEALTH_JS)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)
                blocked = await check_captcha(page)
                print(f"  {label}: {'BLOCKED' if blocked else 'OK'}")
            except Exception as e:
                print(f"  {label}: ERROR {str(e)[:50]}")

            await context.close()

        await browser.close()


# ── Main ──────────────────────────────────────────────────
async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Anjuke anti-bot boundary experiment")
    parser.add_argument("--exp", type=int, default=0, help="Experiment number (0=all)")
    args = parser.parse_args()

    experiments = [
        ("Rate Limit", exp1_rate_limit),
        ("Session Duration", exp2_session_duration),
        ("Recovery", exp3_recovery),
        ("Stealth JS", exp4_stealth),
        ("Cookie Domain", exp5_cookie_domain),
    ]

    if args.exp > 0:
        name, func = experiments[args.exp - 1]
        await func()
    else:
        for name, func in experiments:
            try:
                await func()
            except Exception as e:
                print(f"  Experiment '{name}' error: {e}")

    print("\n" + "=" * 60)
    print("All experiments complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
