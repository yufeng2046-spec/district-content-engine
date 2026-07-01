"""Research phase: assemble structured research brief from DB data + local knowledge."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.connection import get_db
from config import REGION_ID, REGION_NAME, CITY_NAME, PROVINCE

DOUYIN_CACHE = None


def _load_douyin() -> dict:
    """Load cached Douyin content (lazy, cached in memory)."""
    global DOUYIN_CACHE
    if DOUYIN_CACHE is None:
        path = Path(__file__).resolve().parent.parent / "data" / "douyin_content.json"
        if path.exists():
            try:
                DOUYIN_CACHE = json.loads(path.read_text())
            except (json.JSONDecodeError, KeyError):
                DOUYIN_CACHE = {"results": [], "summary": {}}
        else:
            DOUYIN_CACHE = {"results": [], "summary": {}}
    return DOUYIN_CACHE


def _douyin_for_community(community_name: str) -> list[str]:
    """Get Douyin snippets that mention a specific community."""
    data = _load_douyin()
    snippets = []
    for item in data.get("results", []):
        desc = item.get("desc", "")
        if community_name in desc:
            # Extract a clean snippet
            snippet = desc[:120].strip()
            if len(desc) > 120:
                snippet += "..."
            snippets.append(snippet)
    return snippets[:3]  # Max 3 snippets


def _douyin_summary() -> str:
    """Build a summary of Douyin local voices for the region brief."""
    data = _load_douyin()
    results = data.get("results", [])
    if not results:
        return "（暂无抖音本地数据，请运行 python3 data/fetch_douyin.py）"

    # Collect complaint snippets
    complaints = [r["desc"][:100] for r in results if r.get("type") == "complaint"][:5]

    # Collect price talk
    price_talks = [r["desc"][:100] for r in results if r.get("type") == "price_talk"][:5]

    # Top community mentions from cross-referenced DB
    summary_lines = [
        f"共采集{len(results)}条杨凌本地房产相关内容。",
    ]
    if complaints:
        summary_lines.append(f"\n本地吐槽/避坑 ({len(complaints)}条):")
        for c in complaints:
            summary_lines.append(f"  - {c}")
    if price_talks:
        summary_lines.append(f"\n价格讨论 ({len(price_talks)}条):")
        for p in price_talks:
            summary_lines.append(f"  - {p}")

    summary_lines.append(f"\n热门本地中介账号：李优秀｜杨凌锦恒房产、杨凌悦安巢二手房翟翟、杨凌瑞雪探房")
    return "\n".join(summary_lines)


def assemble_community_brief(community_id: str) -> str:
    """Build research brief for Track A (community tour)."""
    conn = get_db()

    comm = conn.execute(
        "SELECT * FROM communities WHERE community_id = ?", (community_id,)
    ).fetchone()

    if not comm:
        conn.close()
        return f"# 错误：未找到小区 {community_id}"

    # POI data grouped by type
    pois = conn.execute(
        "SELECT poi_type, poi_name, distance_m, walk_time_min FROM community_poi WHERE community_id = ? ORDER BY poi_type, distance_m",
        (community_id,),
    ).fetchall()
    conn.close()

    # Group POIs
    poi_map: dict[str, list] = {}
    for p in pois:
        poi_map.setdefault(p["poi_type"], []).append(p)

    # Format POI lines
    def fmt_poi(cat: str, label: str) -> str:
        items = poi_map.get(cat, [])
        if not items:
            return f"  {label}：暂无数据"
        return "\n".join(
            f"  - {p['poi_name']}：{p['distance_m']}米（步行约{p['walk_time_min']}分钟）"
            for p in items[:3]
        )

    # Parse JSON fields safely
    def safe_json(val, default=None):
        if val is None:
            return default or []
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return [val] if val else (default or [])

    unit_sizes = safe_json(comm["unit_sizes"])
    features = safe_json(comm["features"])
    building_types = safe_json(comm["building_types"])

    lines = [
        f"# 研究简报：{comm['name']}",
        "",
        "## 小区硬指标",
        f"- 地址：{comm['address'] or '待查'}",
        f"- 建成年代：{comm['year_built'] or '待查'}年",
        f"- 开发商：{comm['developer'] or '待查'}",
        f"- 物业公司：{comm['property_mgmt'] or '待查'}",
        f"- 物业费：{comm['property_fee'] or '待查'}元/平/月",
        f"- 容积率：{comm['floor_area_ratio'] or '待查'}",
        f"- 绿化率：{comm['green_ratio'] or '待查'}%",
        f"- 车位比：{comm['parking_ratio'] or '待查'}",
        f"- 总户数：{comm['total_units'] or '待查'}户",
    ]

    if building_types:
        types_str = "、".join(building_types) if isinstance(building_types, list) else building_types
        lines.append(f"- 建筑类型：{types_str}")

    if unit_sizes:
        layouts = "、".join(
            f"{u.get('layout', '')}({u.get('area', '')}平)" for u in unit_sizes[:5]
        )
        lines.append(f"- 主力户型：{layouts}")

    if features:
        feat_str = "、".join(features) if isinstance(features, list) else features
        lines.append(f"- 小区特色：{feat_str}")

    lines += [
        "",
        "## 在售情况",
        f"- 挂牌均价：{comm['avg_price'] or '待查'}元/平",
        f"- 在售套数：{comm['listing_count'] or '待查'}套",
        "",
        "## 周边配套",
        f"### 教育",
        fmt_poi("小学", "小学"),
        fmt_poi("初中", "初中"),
        fmt_poi("高中", "高中"),
        fmt_poi("大学", "大学"),
        "",
        f"### 交通",
        fmt_poi("公交站", "公交站"),
        fmt_poi("火车站", "火车站/高铁站"),
        fmt_poi("高速口", "高速口"),
        "",
        f"### 生活",
        fmt_poi("综合医院", "医院"),
        fmt_poi("购物中心", "商场"),
        fmt_poi("超市", "超市"),
        fmt_poi("菜市场", "菜市场"),
        fmt_poi("公园", "公园"),
        "",
        "## 区域背景",
        f"- {REGION_NAME}，{PROVINCE}省{CITY_NAME}市",
        f"- 国家级杨凌农业高新技术产业示范区",
        f"- 核心人群：西北农林科技大学教职工、示范区公务员、农业企业人员",
        f"- 交通特点：无地铁，依赖公交+驾车，陇海铁路杨陵站、G30连霍高速杨凌出口",
        "",
        "## 本地声音（抖音）",
    ]

    # Douyin snippets for this community
    douyin_snippets = _douyin_for_community(comm["name"])
    if douyin_snippets:
        for ds in douyin_snippets:
            lines.append(f"- {ds}")
    else:
        lines.append("（暂无该小区的抖音内容）")

    lines += [
        "",
        "---",
        f"数据来源：{comm['data_source']}，更新于{comm['data_updated']}",
    ]

    return "\n".join(lines)


def assemble_region_brief() -> str:
    """Build research brief for Track B (region commentary)."""
    conn = get_db()

    # Only use communities with real Anjuke data
    communities = conn.execute(
        "SELECT name, avg_price, listing_count FROM communities WHERE avg_price IS NOT NULL OR listing_count IS NOT NULL"
    ).fetchall()

    # Aggregate stats
    prices = [c["avg_price"] for c in communities if c["avg_price"]]
    listings = [c["listing_count"] for c in communities if c["listing_count"]]
    avg_price_str = f"约{sum(prices)/len(prices):.0f}元/平" if prices else "暂无数据（需安居客补充）"
    total_listings_str = str(sum(listings)) if listings else "暂无数据"

    # Total communities (including Gaode-only ones for area context)
    total_all = conn.execute("SELECT COUNT(*) as n FROM communities").fetchone()["n"]
    conn.close()

    comm_list = "\n".join(
        f"- {c['name']}：{c['avg_price'] or '暂无价格数据'}元/平，在售{c['listing_count'] or '暂无'}套"
        for c in communities[:15]
    )

    lines = [
        f"# 研究简报：{REGION_NAME}区域分析",
        "",
        "## 区域概况",
        f"- 归属：{PROVINCE}省{CITY_NAME}市{REGION_NAME}",
        f"- 特殊身份：国家级杨凌农业高新技术产业示范区",
        f"- 核心产业：农业科技、生物育种、高等教育",
        f"- 核心雇主：西北农林科技大学、杨凌示范区管委会、农业科技企业",
        f"- 交通：无地铁，依赖公交+驾车，陇海铁路杨陵站，G30连霍高速",
        "",
        "## 市场数据",
        f"- 区域均价：{avg_price_str}（{len(communities)}个有数据小区样本，共{total_all}个小区）",
        f"- 在售总套数：{total_listings_str}",
        "",
        "## 小区列表",
        comm_list or "（暂无有价格的房源数据，请先运行安居客爬虫）",
        "",
        "## 购房人群画像",
        "- 西农大教职工（青年教师首套、教授改善）",
        "- 示范区公务员/事业单位（稳定收入，偏好单位附近）",
        "- 农业企业员工（预算有限，看重性价比）",
        "- 外地来杨凌务工/经商（低总价门槛）",
        "- 学生家长（陪读需求，租房为主）",
        "",
        "## 区域优势",
        "- 农科城独特定位，政策稳定性强",
        "- 西农大带来稳定人口和消费力",
        "- 总价门槛低（相比咸阳市区和西安）",
        "- 自贸片区政策利好",
        "- 生态环境好，宜居",
        "",
        "## 区域短板",
        "- 距西安主城区较远（约80公里，驾车1.5小时）",
        "- 城市配套弱（无大型商业综合体、无地铁）",
        "- 优质学区集中在西农大附属学校",
        "- 产业单一，人口增长有限",
        "- 房价增值空间有限",
        "",
        "## 本地声音（抖音）",
        _douyin_summary(),
        "",
        "---",
        f"数据来源：安居客+高德+抖音，{len(communities)}个有价格小区，共{total_all}个小区",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test
    conn = get_db()
    rows = conn.execute("SELECT community_id, name FROM communities LIMIT 1").fetchall()
    conn.close()
    if rows:
        cid = rows[0]["community_id"]
        print(f"Testing with: {rows[0]['name']}")
        brief = assemble_community_brief(cid)
        print(brief[:500])
    else:
        print("No communities in DB yet. Scrape first.")
        print("\nRegion brief preview:")
        print(assemble_region_brief()[:500])
