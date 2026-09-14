"""Feishu captcha notification — sends alert when captcha needs human solving."""
import json, requests, os
from datetime import datetime
from pathlib import Path

WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/bb7f59f4-9b6e-444f-aea6-f8b2c6397adc"


def send_captcha_alert(region: str, url: str, screenshot_path: str, page_type: str = "detail"):
    """Send Feishu card notification when captcha detected."""
    ts = datetime.now().strftime("%H:%M:%S")

    card_content = (
        f"**⚠️ 验证码拦截**\n\n"
        f"区域：{region}\n"
        f"页面：{page_type} 页\n"
        f"时间：{ts}\n"
        f"截图：{screenshot_path}\n\n"
        f"请在 Chrome 窗口中手动完成验证，完成后爬虫自动恢复。"
    )

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"⚠️ 验证码 - {region}"},
                "subtitle": {"tag": "plain_text", "content": f"{ts} | {page_type}"},
                "template": "red",
            },
            "elements": [{
                "tag": "div",
                "text": {"tag": "lark_md", "content": card_content},
            }],
        },
    }
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        print(f"    📨 飞书通知已发送: {r.json().get('code')}")
    except Exception as e:
        print(f"    ⚠️ 飞书通知失败: {e}")


def send_progress_update(title: str, content: str):
    """Send a general progress card."""
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "subtitle": {"tag": "plain_text", "content": datetime.now().strftime("%m-%d %H:%M")},
                "template": "blue",
            },
            "elements": [{
                "tag": "div",
                "text": {"tag": "lark_md", "content": content},
            }],
        },
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10)
    except Exception:
        pass


if __name__ == "__main__":
    send_captcha_alert("test", "https://test.com", "/tmp/test.png", "detail")
    print("Test notification sent")
