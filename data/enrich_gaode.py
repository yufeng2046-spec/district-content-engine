"""
Enrich communities with POI data from Gaode API.
For each community in DB, search surrounding: schools, hospitals, transit, shopping.

Usage:
    PYTHONPATH=. python3 data/enrich_gaode.py              # enrich all communities
    PYTHONPATH=. python3 data/enrich_gaode.py --dry-run    # show what would be searched
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.connection import get_db
from data.gaode_client import search_poi, walking_distance
from config import REGION_ID

# POI categories to search for each community
POI_CATEGORIES = [
    # (poi_type, keywords, types_code, radius_m)
    ("小学", "小学", "", 1500),
    ("初中", "中学", "", 1500),
    ("高中", "高中", "", 2000),
    ("大学", "大学", "", 3000),
    ("综合医院", "医院", "090101", 3000),
    ("超市", "超市", "", 1000),
    ("购物中心", "购物中心|商场", "060100", 3000),
    ("公交站", "公交站", "150300", 1000),
    ("火车站", "火车站|高铁站", "150200", 5000),
    ("高速口", "高速出口|高速入口", "150600", 5000),
    ("公园", "公园", "110100", 2000),
    ("菜市场", "菜市场|农贸市场", "", 1500),
]

# Negative POIs (optional, for finding community drawbacks)
NEGATIVE_POI = [
    ("变电站", "变电站", "", 500),
    ("高压线", "高压线|高压电塔", "", 500),
    ("垃圾站", "垃圾中转站|垃圾处理", "", 500),
    ("铁路", "铁路", "150200", 300),
]


def enrich_community(community: dict, dry_run: bool = False) -> int:
    """Enrich a single community with POI data. Returns number of POIs found."""
    cid = community["community_id"]
    name = community["name"]
    lng = community["coordinate_lng"] if community["coordinate_lng"] else None
    lat = community["coordinate_lat"] if community["coordinate_lat"] else None

    if not lng or not lat:
        print(f"  SKIP {name}: no coordinates")
        return 0

    conn = get_db()
    total = 0

    for poi_type, keywords, types_code, radius in POI_CATEGORIES:
        if dry_run:
            print(f"  Would search: {poi_type} ({keywords}) radius={radius}m")
            total += 1
            continue

        try:
            results = search_poi(lng, lat, keywords=keywords, radius=radius, types=types_code, limit=3)
            for r in results:
                dist = r["distance_m"]
                walk_time = int(dist / 80) + 1
                notes = str(r.get("address", "") or "")

                conn.execute(
                    """INSERT OR REPLACE INTO community_poi
                       (community_id, poi_type, poi_name, distance_m, walk_time_min, notes)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (cid, poi_type, r["name"], dist, walk_time, notes),
                )
                total += 1
            time.sleep(0.5)  # Rate limit: 2 QPS for free tier
        except Exception as e:
            print(f"    Gaode error for {poi_type}: {e}")
            time.sleep(1.0)

    # Negative POI (skip for MVP/dry_run by default)
    # for poi_type, keywords, types_code, radius in NEGATIVE_POI:
    #     ...

    conn.commit()
    conn.close()
    return total


def main():
    dry_run = "--dry-run" in sys.argv

    conn = get_db()
    communities = conn.execute(
        "SELECT * FROM communities WHERE coordinate_lng IS NOT NULL"
    ).fetchall()
    conn.close()

    if not communities:
        print("No communities with coordinates in DB. Scrape first.")
        return

    print(f"Enriching {len(communities)} communities with Gaode POI data...")
    if dry_run:
        print("(DRY RUN — no API calls)")

    grand_total = 0
    for row in communities:
        c = dict(row)
        name = c["name"]
        print(f"\n  {name} ({c.get('coordinate_lng')}, {c.get('coordinate_lat')})")
        found = enrich_community(c, dry_run=dry_run)
        print(f"    -> {found} POIs")
        grand_total += found
        if not dry_run:
            time.sleep(0.5)

    print(f"\nDone. Total POIs: {grand_total}")


if __name__ == "__main__":
    main()
