"""Research phase: assemble structured research brief from DB data + local knowledge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.connection import get_db
from config import get_region, DEFAULT_REGION

def _query_region_id(region_name: str | None = None) -> str | None:
    """Map a Chinese region name back to its region_id for DB filtering."""
    if not region_name:
        return None
    from config import REGIONS
    for rid, rcfg in REGIONS.items():
        if rcfg["name"] == region_name:
            return rid
    # Try direct match
    if region_name in REGIONS:
        return region_name
    return None


def _douyin_for_community(community_name: str, region_id: str | None = None) -> list[str]:
    """Get Douyin snippets that mention a specific community, filtered by region."""
    conn = get_db()
    try:
        if region_id:
            rows = conn.execute(
                "SELECT desc FROM douyin_local_content WHERE region_id = ? ORDER BY digg_count DESC",
                (region_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT desc FROM douyin_local_content ORDER BY digg_count DESC"
            ).fetchall()
        snippets = []
        for row in rows:
            desc = row["desc"]
            if community_name in desc:
                snippet = desc[:120].strip()
                if len(desc) > 120:
                    snippet += "..."
                snippets.append(snippet)
        return snippets[:3]
    finally:
        conn.close()


def _douyin_summary(region_name: str | None = None, region_id: str | None = None) -> str:
    """Build a summary of Douyin local voices, filtered by region."""
    conn = get_db()
    region_label = region_name or "本地"

    try:
        rid = region_id or _query_region_id(region_name)
        if rid:
            total = conn.execute(
                "SELECT COUNT(*) as n FROM douyin_local_content WHERE region_id = ?", (rid,)
            ).fetchone()["n"]
            complaints = [
                row["desc"][:100]
                for row in conn.execute(
                    "SELECT desc FROM douyin_local_content WHERE region_id = ? AND type = 'complaint' ORDER BY digg_count DESC LIMIT 5",
                    (rid,),
                ).fetchall()
            ]
            price_talks = [
                row["desc"][:100]
                for row in conn.execute(
                    "SELECT desc FROM douyin_local_content WHERE region_id = ? AND type = 'price_talk' ORDER BY digg_count DESC LIMIT 5",
                    (rid,),
                ).fetchall()
            ]
        else:
            total = conn.execute("SELECT COUNT(*) as n FROM douyin_local_content").fetchone()["n"]
            complaints = [
                row["desc"][:100]
                for row in conn.execute(
                    "SELECT desc FROM douyin_local_content WHERE type = 'complaint' ORDER BY digg_count DESC LIMIT 5"
                ).fetchall()
            ]
            price_talks = [
                row["desc"][:100]
                for row in conn.execute(
                    "SELECT desc FROM douyin_local_content WHERE type = 'price_talk' ORDER BY digg_count DESC LIMIT 5"
                ).fetchall()
            ]
    finally:
        conn.close()

    if total == 0:
        return f"（暂无抖音{region_label}数据，请运行 python3 data/fetch_douyin.py --region {rid or 'default'}）"

    summary_lines = [
        f"共采集{total}条{region_label}房产相关内容。",
    ]
    if complaints:
        summary_lines.append(f"\n本地吐槽/避坑 ({len(complaints)}条):")
        for c in complaints:
            summary_lines.append(f"  - {c}")
    if price_talks:
        summary_lines.append(f"\n价格讨论 ({len(price_talks)}条):")
        for p in price_talks:
            summary_lines.append(f"  - {p}")

    return "\n".join(summary_lines)


def assemble_community_brief(community_id: str, region_id: str | None = None) -> str:
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

    # Resolve region context
    resolved_region_id = region_id or comm.get("region_id") or DEFAULT_REGION
    r = get_region(resolved_region_id)
    region_name = r["name"]
    city_name = r["city"]
    province = r["province"]

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
        f"- {region_name}，{province}{'省' if province != city_name else '市'}{city_name if province != city_name else ''}",
        f"- 详细区域背景请参考城市底色文档：output/{r['id']}_brief.md",
        "",
        "## 本地声音（抖音）",
    ]

    # Douyin snippets for this community
    douyin_snippets = _douyin_for_community(comm["name"], region_id=resolved_region_id)
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


def assemble_region_brief(region_id: str | None = None) -> str:
    """Build research brief for Track B (region commentary)."""
    r = get_region(region_id)
    region_name = r["name"]
    city_name = r["city"]
    province = r["province"]
    resolved_id = r["id"]

    conn = get_db()

    # Only use communities with real Anjuke data, filtered by region
    communities = conn.execute(
        "SELECT name, avg_price, listing_count FROM communities WHERE (avg_price IS NOT NULL OR listing_count IS NOT NULL) AND region_id = ?",
        (resolved_id,)
    ).fetchall()

    # Aggregate stats
    prices = [c["avg_price"] for c in communities if c["avg_price"]]
    listings = [c["listing_count"] for c in communities if c["listing_count"]]
    avg_price_str = f"约{sum(prices)/len(prices):.0f}元/平" if prices else "暂无数据（需安居客补充）"
    total_listings_str = str(sum(listings)) if listings else "暂无数据"

    # Total communities in this region
    total_all = conn.execute("SELECT COUNT(*) as n FROM communities WHERE region_id = ?", (resolved_id,)).fetchone()["n"]
    conn.close()

    comm_list = "\n".join(
        f"- {c['name']}：{c['avg_price'] or '暂无价格数据'}元/平，在售{c['listing_count'] or '暂无'}套"
        for c in communities[:15]
    )

    lines = [
        f"# 研究简报：{region_name}区域分析",
        "",
        "## 区域概况",
        f"- 归属：{province}{'省' if province != city_name else '市'}{city_name if province != city_name else ''}{region_name}",
        f"- 区域背景请参考城市底色文档：output/{resolved_id}_brief.md",
        "",
        "## 市场数据",
        f"- 区域均价：{avg_price_str}（{len(communities)}个有数据小区样本，共{total_all}个小区）",
        f"- 在售总套数：{total_listings_str}",
        "",
        "## 小区列表",
        comm_list or "（暂无有价格的房源数据，请先运行安居客爬虫）",
        "",
        "## 购房人群画像",
        "（请参考该区域的城市底色事实库获取当地购房人群画像）",
        "",
        "## 区域特点",
        "（请参考城市底色事实库和商圈brief文档获取区域优势与短板）",
        "",
        "## 本地声音（抖音）",
        _douyin_summary(region_name, region_id=resolved_id),
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
