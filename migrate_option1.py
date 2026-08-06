#!/usr/bin/env python3
"""选项1迁移: cities 定稿为物理地级市。

1. 重分类 15 个自治州/地区 (阿坝/阿克苏/…): county → prefecture (误分类修复)
2. 删除 cities 里其余 335 个县级子域
3. 保存县级子域 → data/anjuke_county_map.json (含父地级市/省直辖标记)
4. districts 加 type/gb_code/anjuke_subdomain 列, 为重叠县级补 anjuke_subdomain
5. communities 加 district_id 列, 填充 = region_id (区县级爬取的)

原则: 不臆想 — 未爬取的县级子域不造 district 行 (避免未来 slug 不匹配返工),
存到参考文件, 真爬到时再实例化。
"""
from __future__ import annotations  # Python 3.9: 延迟求值类型注解

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from db.connection import get_db
from db.schema import create_tables
from config import REGIONS
import data  # noqa

AUTO = json.loads((BASE_DIR / "data" / "auto_regions.json").read_text())
ALL_REGIONS = {**REGIONS, **AUTO}

GB_CITIES = json.loads((BASE_DIR.parent.parent / "tmp" / "gb_cities.json").read_text()) if (BASE_DIR.parent.parent / "tmp" / "gb_cities.json").exists() else []
if not GB_CITIES:
    GB_CITIES = json.loads(Path("/tmp/gb_cities.json").read_text())
PREFECTURES = [c for c in GB_CITIES if c["name"] != "市辖区"]

GB_AREAS = json.loads(Path("/tmp/gb_areas.json").read_text())


def find_prefecture(name: str) -> dict | None:
    """name 是某个地级(自治州/地区/地级市)全名的前缀时返回该地级."""
    for c in PREFECTURES:
        if c["name"].startswith(name):
            return c
    return None


def main():
    create_tables()
    conn = get_db()

    # ═══ 1. 重分类 15 个自治州/地区 → prefecture ═══
    reclassified = []
    for r in conn.execute("SELECT city_id, name FROM cities WHERE level='county'").fetchall():
        pref = find_prefecture(r["name"])
        if pref:
            conn.execute(
                "UPDATE cities SET level='prefecture', gb_name=?, gb_city_code=?, gb_area_code=NULL WHERE city_id=?",
                (pref["name"], pref["code"], r["city_id"]))
            reclassified.append(r["city_id"])
    conn.commit()
    print(f"重分类为地级: {len(reclassified)}")

    # ═══ 2. 剩余的县级 → 移出 cities, 存参考文件 ═══
    county_map = {}
    for r in conn.execute("SELECT city_id, name, gb_name, gb_city_code, gb_area_code, province_id FROM cities WHERE level='county'").fetchall():
        parent_city = None
        if r["gb_city_code"]:
            # 父地级市: cities 里 gb_city_code == 该县级 gb_city_code 的地级
            pc = conn.execute("SELECT city_id FROM cities WHERE gb_city_code=? AND level IN ('prefecture','province') LIMIT 1",
                              (r["gb_city_code"],)).fetchone()
            if pc:
                parent_city = pc[0]
        county_map[r["city_id"]] = {
            "name": r["name"], "gb_name": r["gb_name"],
            "gb_city_code": r["gb_city_code"], "gb_area_code": r["gb_area_code"],
            "province_id": r["province_id"], "parent_city_id": parent_city,
        }
    n_county = len(county_map)
    Path("data/anjuke_county_map.json").write_text(
        json.dumps(county_map, ensure_ascii=False, indent=1))
    conn.execute("DELETE FROM cities WHERE level='county'")
    conn.commit()
    print(f"县级移出 cities: {n_county} → data/anjuke_county_map.json")

    # ═══ 3. districts 加列 ═══
    for col, ddl in [
        ("type", "ALTER TABLE districts ADD COLUMN type TEXT"),
        ("gb_code", "ALTER TABLE districts ADD COLUMN gb_code TEXT"),
        ("anjuke_subdomain", "ALTER TABLE districts ADD COLUMN anjuke_subdomain TEXT"),
    ]:
        try:
            conn.execute(ddl)
        except Exception:
            pass  # 已存在
    conn.commit()

    # ═══ 4. 为重叠县级补 anjuke_subdomain (子域 == 该县级在 anjuke_county_map 的 key) ═══
    # 匹配: 县级子域的名字+父市 对应 已有 district 的名字+城市
    for sub, info in county_map.items():
        parent = info.get("parent_city_id")
        if not parent:
            continue
        d = conn.execute(
            "SELECT district_id FROM districts WHERE city=? AND name=? LIMIT 1",
            (parent, info["name"])).fetchone()
        if d:
            conn.execute("UPDATE districts SET anjuke_subdomain=? WHERE district_id=?",
                         (sub, d["district_id"]))
    conn.commit()

    # ═══ 5. communities 加 district_id + 填充 ═══
    try:
        conn.execute("ALTER TABLE communities ADD COLUMN district_id TEXT")
    except Exception:
        pass
    filled = conn.execute("""
        UPDATE communities SET district_id = region_id
        WHERE region_id IN (SELECT district_id FROM districts)
    """).rowcount
    conn.commit()
    print(f"communities.district_id 填充: {filled}")

    # ═══ 6. 校验 ═══
    print()
    print("=== 迁移后校验 ===")
    print("cities:", conn.execute("SELECT COUNT(*) FROM cities").fetchone()[0], "(应=334地级+4直辖市=338)")
    for r in conn.execute("SELECT level, COUNT(*) FROM cities GROUP BY 1").fetchall():
        print(f"  {r[0]}: {r[1]}")
    print("districts:", conn.execute("SELECT COUNT(*) FROM districts").fetchone()[0])
    print("communities 有 district_id:",
          conn.execute("SELECT COUNT(*) FROM communities WHERE district_id IS NOT NULL").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
