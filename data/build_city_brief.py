"""
Build a consolidated city background document from cached WeChat articles.
Filters noise, groups by category, and outputs per-商圈 structured markdown
that Claude can use as a fact library for script writing.

Usage:
    PYTHONPATH=. python3 data/build_city_brief.py --region datong_pingcheng
    PYTHONPATH=. python3 data/build_city_brief.py --region datong_pingcheng --shangquan 万达
"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_region, DEFAULT_REGION

BASE_DIR = Path(__file__).resolve().parent.parent

# Generic category classifier: keyword patterns → category
CATEGORY_RULES = [
    (r"买房|楼盘|新房|房价|房产|二手房|小区|房源", "房产市场"),
    (r"城市[规计]划|区域.*发[展布]|空间[规布]局", "城市规划"),
    (r"经济|产业|工[业园]区|企[业商]|招商引资", "经济产业"),
    (r"农高会|农博|展览|展会|UFI", "农高会/展会"),
    (r"上合|SCO|国际合作|一带一路|外[交事]|培训基地", "国际合作"),
    (r"自贸|保税|综保区|口岸|通关|跨境", "自贸保税"),
    (r"大学|学院|高校|人才|科教|科研|学术", "高校人才"),
    (r"高铁|铁路|交通|地铁|高速|公路|枢纽|机场", "交通基建"),
    (r"医院|医疗|卫生|健康|三甲|医保", "医疗资源"),
    (r"万达|商业|商圈|购物|超市|消费|夜经济|餐饮", "商业生活"),
    (r"宜居|生态|公园|绿[化地]|环境|空气|水[系景]", "宜居生活"),
    (r"人口|落户|户[籍政]|城镇化|农民[工入]", "人口发展"),
    (r"古城|文旅|旅游|文化[遗产]|历史|景区|云冈", "文旅古城"),
    (r"古城.*保护|旧城.*改造|城市更新|棚改", "城市更新"),
]

def classify_article(title: str, text: str, query: str) -> str:
    """Classify article into a category based on title + query + text."""
    combined = title + " " + query + " " + text[:500]
    for pattern, category in CATEGORY_RULES:
        if re.search(pattern, combined):
            return category
    return "其他"

def main():
    region_id = DEFAULT_REGION
    shangquan = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--region" and i + 1 < len(args):
            region_id = args[i + 1]; i += 2
        elif args[i] == "--shangquan" and i + 1 < len(args):
            shangquan = args[i + 1]; i += 2
        else:
            i += 1

    region = get_region(region_id)
    input_file = BASE_DIR / "data" / f"wechat_{region_id}.json"
    if not input_file.exists():
        print(f"Input file not found: {input_file}")
        print("Run fetch_wechat.py --region {region_id} first.")
        return

    sq_suffix = f"_{shangquan}" if shangquan else ""
    output_file = BASE_DIR / "output" / f"{region_id}{sq_suffix}_brief.md"

    cache = json.loads(input_file.read_text(encoding="utf-8"))

    # Noise patterns from config
    noise_patterns = region.get("wechat_exclude_terms", [])

    def is_noise(title: str, text: str) -> bool:
        for pat in noise_patterns:
            if re.search(pat, title) or re.search(pat, text[:200]):
                return True
        return False

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

        # 商圈 filter: if shangquan specified, only keep articles mentioning it
        if shangquan and shangquan not in title and shangquan not in text[:500]:
            continue

        stats["kept"] += 1
        query = article.get("query", "其他")
        category = classify_article(title, text, query)

        by_category[category].append({
            "title": title,
            "account": article.get("account", ""),
            "publish_time": article.get("publish_time", ""),
            "text": text,
            "query": query,
        })

    print(f"Total: {stats['total']}, Noise: {stats['noise']}, Empty: {stats['empty']}, Kept: {stats['kept']}")

    # Build output
    city_name = region["city"]
    district_name = region["name"]
    sq_label = f" {shangquan}商圈" if shangquan else ""
    lines = []
    lines.append(f"# {city_name}{district_name}{sq_label} 城市底色参考文档")
    lines.append(f"\n**生成时间**: 2026-07-02")
    lines.append(f"**数据来源**: 微信公众号搜狗搜索，{stats['kept']} 篇有效文章，共 {len(by_category)} 个类别")
    lines.append(f"**区域**: {city_name} {district_name}{sq_label}")
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
            text = art['text']
            if len(text) > 3000:
                text = text[:3000] + f"\n\n... (截断，原文共 {len(art['text'])} 字符)"
            lines.append(text)
            lines.append("")

    output_file.parent.mkdir(exist_ok=True)
    output_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written to {output_file}")
    print(f"Total chars: {len(output_file.read_text(encoding='utf-8'))}")

if __name__ == "__main__":
    main()
