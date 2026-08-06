#!/usr/bin/env python3
"""回填: 把已爬数据挂到 省→市→区 层级。

1. communities 加 city_id/province_id (从 region_id 前缀映射, yangling→xianyang)
2. districts 补全 (langfang 3 区 + 杨凌) + 挂到城市/省
3. 报告映射结果, 便于后续对抗性审查
"""
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from db.connection import get_db
from db.schema import create_tables

# region_id 前缀 → city_id (安居客子域). yangling 是咸阳的区, 不独立成市.
REGION_CITY = {
    "beijing": "beijing", "chengdu": "chengdu", "xa": "xa", "shanghai": "shanghai",
    "langfang": "langfang", "datong": "datong", "shenzhen": "shenzhen",
    "guangzhou": "guangzhou", "yangling": "xianyang",
}

# 需补的 district (region_id, city_id, 中文区名, 城市中文名, slug, url)
MISSING_DISTRICTS = [
    ("langfang_dachang", "langfang", "大厂", "廊坊", "dachang", "https://langfang.anjuke.com/community/dachang/"),
    ("langfang_sanhe",   "langfang", "三河", "廊坊", "sanhe",   "https://langfang.anjuke.com/community/sanhe/"),
    ("langfang_xianghe", "langfang", "香河", "廊坊", "xianghe", "https://langfang.anjuke.com/community/xianghe/"),
    ("yangling",         "xianyang", "杨陵", "咸阳", "yangling", "https://xianyang.anjuke.com/community/yangling/"),
]


def main():
    create_tables()
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ═══ 1. 补 districts (langfang + yangling) ═══
    added = 0
    for district_id, city_id, name, city_name, slug, url in MISSING_DISTRICTS:
        exists = conn.execute("SELECT 1 FROM districts WHERE district_id=?", (district_id,)).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO districts (district_id, city, city_name, name, slug, url, source_file, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (district_id, city_id, city_name, name, slug, url, "backfill_province_city", now))
            added += 1
    print(f"补 districts: {added} 行 (langfang 3 + yangling)")

    # ═══ 2. districts → city_id/province_id ═══
    d_upd = 0
    for d in conn.execute("SELECT district_id, city FROM districts").fetchall():
        city_id = REGION_CITY.get(d["city"], d["city"])
        prov = conn.execute("SELECT province_id FROM cities WHERE city_id=?", (city_id,)).fetchone()
        if prov:
            conn.execute("UPDATE districts SET city_id=?, province_id=? WHERE district_id=?",
                         (city_id, prov["province_id"], d["district_id"]))
            d_upd += 1
        else:
            print(f"  ⚠️ district {d['district_id']}: 城市 {city_id} 不在 cities 表")
    print(f"districts 挂城市/省: {d_upd}/{d_upd}")

    # ═══ 3. communities → city_id/province_id ═══
    c_upd = 0
    c_miss = []
    regions = conn.execute("SELECT DISTINCT region_id FROM communities").fetchall()
    for r in regions:
        region_id = r["region_id"]
        prefix = region_id.split("_")[0] if "_" in region_id else region_id
        city_id = REGION_CITY.get(prefix, prefix)
        prov = conn.execute("SELECT province_id FROM cities WHERE city_id=?", (city_id,)).fetchone()
        if not prov:
            c_miss.append(region_id)
            continue
        conn.execute("UPDATE communities SET city_id=?, province_id=? WHERE region_id=?",
                     (city_id, prov["province_id"], region_id))
        c_upd += 1
    conn.commit()
    conn.close()
    print(f"communities 挂城市/省: {c_upd} 个 region")
    if c_miss:
        print(f"  ⚠️ 无法映射的 region: {c_miss}")

    # ═══ 4. 校验覆盖 ═══
    conn = get_db()
    t = conn.execute("SELECT COUNT(*) FROM communities").fetchone()[0]
    with_p = conn.execute("SELECT COUNT(*) FROM communities WHERE province_id IS NOT NULL").fetchone()[0]
    print(f"\n校验: 小区 {t:,} | 有省 {with_p:,} ({with_p/t*100:.1f}%)")
    conn.close()


if __name__ == "__main__":
    main()
