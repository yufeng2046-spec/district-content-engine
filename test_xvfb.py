"""Test Playwright in virtual display on CubeMini."""
import sys, time, os
sys.path.insert(0, '/home/frank/district-content-engine')

from playwright.sync_api import sync_playwright

print(f"DISPLAY={os.environ.get('DISPLAY', 'NOT SET')}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://www.baidu.com", timeout=15000)
    time.sleep(2)
    page.screenshot(path="/tmp/vnc_test.png")
    print(f"Screenshot: {page.title()}")
    browser.close()
    print("Test OK — browser works in virtual display")
