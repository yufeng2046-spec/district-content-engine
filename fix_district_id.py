#!/usr/bin/env python3
"""Bug 2 修复: 把 districts.district_id 统一为 slug 格式 (chengdu_武侯 → chengdu_wuhou)。

级联更新:
  districts.district_id / name / slug  (仅 chengdu/xa/datong 三个城市需要改)
  shangquans.district_id + shangquan_id
  communities.shangquan_id

slug 来源: district URL 末尾 (community/wuhou/ → wuhou)
中文名来源: config.REGIONS + auto_regions.json
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from db.connection import get_db
from config import REGIONS

AUTO = json.loads((BASE_DIR / "data" / "auto_regions.json").read_text())
ALL_REGIONS = {**REGIONS, **AUTO}

# 只修这三个城市 (district_id/name/slug 反了的)
BROKEN_CITIES = {"chengdu", "xa", "datong"}


def main():
    conn = get_db()

    # ═══ 1. 建 old→new district 映射 (仅 BROKEN_CITIES) ═══
    dist_map = {}   # old_district_id -> new_district_id
    name_fix = {}   # old_district_id -> 中文名
    slug_fix = {}   # old_district_id -> english slug
    for r in conn.execute("SELECT district_id, city, url FROM districts").fetchall():
        if r["city"] not in BROKEN_CITIES:
            continue
        url_slug = r["url"].rstrip("/").split("/")[-1] if r["url"] else ""
        if not url_slug:
            print(f"  ⚠️ {r['district_id']} 无 URL slug, 跳过")
            continue
        new_id = f"{r['city']}_{url_slug}"
        cfg = ALL_REGIONS.get(new_id, {})
        cn_name = cfg.get("name", "") or url_slug
        dist_map[r["district_id"]] = new_id
        name_fix[r["district_id"]] = cn_name
        slug_fix[r["district_id"]] = url_slug
    print(f"需要改的 district: {len(dist_map)}")
    if not dist_map:
        print("没有要改的, 退出")
        conn.close()
        return

    # ═══ 2. 建 old→new shangquan_id 映射 ═══
    sq_map = {}   # old_shangquan_id -> new_shangquan_id
    for r in conn.execute("SELECT shangquan_id, district_id, slug FROM shangquans").fetchall():
        if r["district_id"] in dist_map:
            sq_map[r["shangquan_id"]] = f"{dist_map[r['district_id']]}_{r['slug']}"
    print(f"shangquan 需改: {len(sq_map)}")

    # ═══ 3. 更新 communities.shangquan_id ═══
    c_upd = 0
    c_orphan = 0
    for r in conn.execute("SELECT community_id, shangquan_id FROM communities WHERE shangquan_id IS NOT NULL").fetchall():
        old = r["shangquan_id"]
        if old in sq_map:
            conn.execute("UPDATE communities SET shangquan_id=? WHERE community_id=?",
                         (sq_map[old], r["community_id"]))
            c_upd += 1
        elif old.split("_")[0] in BROKEN_CITIES:
            c_orphan += 1   # 理论上不该有 (跨城垃圾已 NULL 掉)
    conn.commit()
    print(f"communities 更新: {c_upd} | 无映射孤儿: {c_orphan}")
    if c_orphan:
        print("  ⚠️ 有孤儿 shangquan_id, 需检查!")

    # ═══ 4. 更新 shangquans ═══
    for old_sq, new_sq in sq_map.items():
        old_dist = old_sq.rsplit("_", 1)[0]
        conn.execute("UPDATE shangquans SET shangquan_id=?, district_id=? WHERE shangquan_id=?",
                     (new_sq, dist_map[old_dist], old_sq))
    conn.commit()

    # ═══ 5. 更新 districts (district_id / name / slug) ═══
    for old_did, new_did in dist_map.items():
        conn.execute("UPDATE districts SET district_id=?, name=?, slug=? WHERE district_id=?",
                     (new_did, name_fix[old_did], slug_fix[old_did], old_did))
    conn.commit()
    conn.close()

    print("\n✅ 迁移完成")


if __name__ == "__main__":
    main()
