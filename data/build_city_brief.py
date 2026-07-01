"""
Build a consolidated city background document from all cached WeChat articles.
Filters noise, groups by category, and outputs a structured markdown file
that Claude can use as a fact library for script writing.
"""
import json
import re
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = BASE_DIR / "data" / "wechat_content.json"
OUTPUT_FILE = BASE_DIR / "output" / "yangling_city_brief_v2.md"

# Noise patterns — skip articles that are just listings or spam
NOISE_PATTERNS = [
    r"出售房屋信息展示",
    r"出租房源信息展示",
    r"精选二手房在售房源",
    r"杨凌在线-出售",
    r"杨凌在线-出租",
    r"最新房源",
    r"好房推荐",
    r"房价出炉.*你家",
    r"最新小区房价",
]

def is_noise(title: str, text: str) -> bool:
    for pat in NOISE_PATTERNS:
        if re.search(pat, title) or re.search(pat, text[:200]):
            return True
    return False

# Category mapping from query keywords
CATEGORY_MAP = {
    "杨凌 买房": "房产市场",
    "杨凌 楼盘 新房": "房产市场",
    "杨凌 房价 走势": "房产市场",
    "杨凌 房产 市场": "房产市场",
    "杨凌 城市规划": "城市规划",
    "杨凌 区域 发展": "区域发展",
    "杨凌 经济 产业": "经济产业",
    "杨凌 农业 科技 示范": "农业科技",
    "杨凌 企业 产业 园区": "产业园区",
    "杨凌 农高会": "农高会",
    "杨凌 上合 农业 组织": "上合组织",
    "杨凌 自贸 保税": "自贸保税",
    "西北农林科技大学 杨凌": "高校人才",
    "杨凌 人才 落户 政策": "高校人才",
    "杨凌 高铁 交通 规划": "交通基建",
    "杨凌 医院 医疗": "医疗资源",
    "杨凌 万达 商业 配套": "商业生活",
    "杨凌 生活 环境 宜居": "宜居生活",
    "杨凌 人口 发展": "人口发展",
}

def main():
    cache = json.loads(INPUT_FILE.read_text(encoding="utf-8"))

    # Filter and group
    by_category = defaultdict(list)
    stats = {"total": len(cache), "noise": 0, "empty": 0, "kept": 0}

    for url, article in cache.items():
        title = article.get("title", "")
        text = article.get("text", "")

        if len(text) < 100:
            stats["empty"] += 1
            continue
        if is_noise(title, text):
            stats["noise"] += 1
            continue

        stats["kept"] += 1
        query = article.get("query", "其他")
        category = CATEGORY_MAP.get(query, "其他")

        by_category[category].append({
            "title": title,
            "account": article.get("account", ""),
            "publish_time": article.get("publish_time", ""),
            "text": text,
            "query": query,
        })

    print(f"Total: {stats['total']}, Noise: {stats['noise']}, Empty: {stats['empty']}, Kept: {stats['kept']}")

    # Build output
    lines = []
    lines.append("# 杨凌城市底色参考文档 v2")
    lines.append(f"\n**生成时间**: 2026-07-01")
    lines.append(f"**数据来源**: 微信公众号搜狗搜索，{stats['kept']} 篇有效文章，共 {len(by_category)} 个类别")
    lines.append("\n---\n")

    # Table of contents
    lines.append("## 目录\n")
    for cat in sorted(by_category.keys()):
        lines.append(f"- [{cat}](#{cat})（{len(by_category[cat])} 篇）")
    lines.append("")

    for category in sorted(by_category.keys()):
        articles = by_category[category]
        lines.append(f"---\n\n## {category}\n")
        lines.append(f"*{len(articles)} 篇文章*\n")

        for i, art in enumerate(articles):
            lines.append(f"### {i+1}. {art['title']}")
            lines.append(f"- 来源: {art['account']} | {art['publish_time']}")
            lines.append(f"- 搜索词: {art['query']}")
            lines.append(f"")
            # Truncate very long articles to 3000 chars for readability
            text = art['text']
            if len(text) > 3000:
                text = text[:3000] + f"\n\n... (截断，原文共 {len(art['text'])} 字符)"
            lines.append(text)
            lines.append("")

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written to {OUTPUT_FILE}")
    print(f"Total chars: {len(OUTPUT_FILE.read_text(encoding='utf-8'))}")

if __name__ == "__main__":
    main()
