#!/usr/bin/env python3
"""构建 provinces / cities 表。

数据源:
  1. 安居客权威城市列表 (从 sy-city.html 抓取, /tmp/sycity_dom.json)
  2. GB/T 2260 标准行政区划 (modood/Administrative-divisions-of-China)
     - /tmp/gb_provinces.json (31 大陆省级)
     - /tmp/gb_cities.json   (342 地级)
     - /tmp/gb_areas.json    (2978 县级)

先分析映射, 打印匹配率和不匹配项, 再落库。
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# ═══ 1. 加载 GB 标准行政区划 ═══
gb_provinces = json.loads(Path("/tmp/gb_provinces.json").read_text())
gb_cities = json.loads(Path("/tmp/gb_cities.json").read_text())
gb_areas = json.loads(Path("/tmp/gb_areas.json").read_text())

# 34 省级: 大陆 31 + 港澳台 3
EXTRA_PROVINCES = [
    {"code": "71", "name": "台湾省", "type": "省"},
    {"code": "81", "name": "香港特别行政区", "type": "特别行政区"},
    {"code": "82", "name": "澳门特别行政区", "type": "特别行政区"},
]
GB_PROVINCE_TYPE = {
    "北京市": "直辖市", "天津市": "直辖市", "上海市": "直辖市", "重庆市": "直辖市",
    "内蒙古自治区": "自治区", "广西壮族自治区": "自治区", "西藏自治区": "自治区",
    "宁夏回族自治区": "自治区", "新疆维吾尔自治区": "自治区",
}

cities_by_name = {c["name"]: c for c in gb_cities if c["name"] != "市辖区"}
areas_by_name = {a["name"]: a for a in gb_areas}
provinces_by_name = {p["name"]: p for p in gb_provinces}

MUNICIPALITY = {  # 直辖市的子域 → 省级码
    "beijing": "11", "shanghai": "31", "tianjin": "12", "chongqing": "50",
}
MUNICIPALITY_GB = {  # 直辖市子域 → GB 全名
    "beijing": "北京市", "shanghai": "上海市", "tianjin": "天津市", "chongqing": "重庆市",
}


def short_province(name):
    for s in ["特别行政区", "壮族自治区", "维吾尔自治区", "回族自治区", "自治区"]:
        name = name.replace(s, "")
    return name.replace("省", "").replace("市", "")

# 人工兜底: 非标准行政区划/特殊名 → (provinceCode, cityCode, areaCode, gb_name)
MANUAL = {
    "燕郊":   ("13", "1310", "131082", "三河市"),       # 河北廊坊三河 (燕郊镇)
    "大亚湾": ("44", "4413", None,     "惠州市"),        # 广东惠州 (大亚湾开发区)
    "明港":   ("41", "4115", "411503", "信阳市平桥区"),  # 河南信阳 (明港镇)
    "加尔玛": (None, None, None, None),                 # 疑似垃圾条目, 无法定位
}

# 自治州/地区前缀后缀: 用 GB 全名前缀匹配
AUTONOMOUS_SUFFIXES = [
    "蒙古自治州", "蒙古族藏族自治州", "藏族自治州", "彝族自治州", "壮族苗族自治州",
    "傣族景颇族自治州", "柯尔克孜自治州", "朝鲜族自治州", "哈尼族彝族自治州",
    "布依族苗族自治州", "土家族苗族自治州", "哈萨克自治州", "黎族苗族自治州",
    "傈僳族自治州", "苗族侗族自治州", "傣族自治州", "自治州", "地区", "林区",
]

def find_gb(name):
    """匹配 GB 数据, 返回 (provinceCode, cityCode, areaCode, gb_name) 或 None."""
    if name in cities_by_name:
        c = cities_by_name[name]
        return c["provinceCode"], c["code"], None, c["name"]
    if name in areas_by_name:
        a = areas_by_name[name]
        return a["provinceCode"], a["cityCode"], a["code"], a["name"]
    # 尝试加后缀: 市/县/区/自治县/旗/镇/盟/州
    for suf in ["市", "县", "区", "自治县", "旗", "镇", "盟", "州"]:
        n2 = name + suf
        if n2 in cities_by_name:
            c = cities_by_name[n2]
            return c["provinceCode"], c["code"], None, c["name"]
        if n2 in areas_by_name:
            a = areas_by_name[n2]
            return a["provinceCode"], a["cityCode"], a["code"], a["name"]
    # 自治州/地区: name 是某个 GB 城市名的前缀
    for cname, c in cities_by_name.items():
        if any(name == cname.replace(s, "") for s in AUTONOMOUS_SUFFIXES):
            return c["provinceCode"], c["code"], None, c["name"]
    # 自治县(陵水黎族自治县 等)
    for aname, a in areas_by_name.items():
        if any(aname.startswith(name + s) for s in ["黎族自治县", "自治县", "自治旗", "林区"]):
            return a["provinceCode"], a["cityCode"], a["code"], a["name"]
    return None

def main():
    # 加载安居客城市列表
    dom = json.loads(Path("/tmp/sycity_dom.json").read_text())
    # A-Z 城市
    letter = {}
    for k, v in dom.items():
        if len(k) == 1 and k.isalpha():
            for e in v:
                # 排除 .fang. 房价内容站 (非真实城市子域)
                if ".fang." in e["href"]:
                    continue
                m = re.match(r"https?://([a-z0-9]+)\.anjuke\.com", e["href"])
                sub = m.group(1) if m else ""
                letter[e["name"]] = sub
    # 其他里有独立子域的 (凯里)
    other_own = {}
    for e in dom.get("其他", []):
        m = re.match(r"https?://([a-z0-9]+)\.anjuke\.com", e["href"])
        sub = m.group(1) if m else ""
        if sub and sub not in letter.values():
            other_own[e["name"]] = sub
    # 热门
    hot = {e["name"] for e in dom.get("热门城市", [])}

    cities = list(letter.items()) + list(other_own.items())
    print(f"安居客城市总数: {len(cities)} (A-Z {len(letter)} + 其他独立子域 {len(other_own)})")

    # 重名碰撞检测: 哪些 GB 名字在多个省份存在
    name_provs = {}
    for a in gb_areas:
        name_provs.setdefault(a["name"], set()).add(a["provinceCode"])
    for c in gb_cities:
        if c["name"] != "市辖区":
            name_provs.setdefault(c["name"], set()).add(c["provinceCode"])
    collisions = {n: sorted(p) for n, p in name_provs.items() if len(p) > 1}

    # 映射
    matched, unmatched, ambiguous = [], [], []
    for name, sub in cities:
        if name in MANUAL:
            pc, ccode, acode, gname = MANUAL[name]
            if pc:
                matched.append((name, sub, pc, ccode, acode, gname))
            else:
                unmatched.append((name, sub))
            continue
        if sub in MUNICIPALITY:
            pc = MUNICIPALITY[sub]
            matched.append((name, sub, pc, None, None, MUNICIPALITY_GB.get(sub, name + "市")))
            continue
        gb = find_gb(name)
        if gb:
            pc, ccode, acode, gname = gb
            # 重名检查: 若 gname 在多省存在, 标为需复核
            if gname in collisions:
                ambiguous.append((name, sub, gname, collisions[gname]))
            matched.append((name, sub, pc, ccode, acode, gname))
        else:
            unmatched.append((name, sub))

    print(f"匹配: {len(matched)} | 未匹配: {len(unmatched)} | 重名需复核: {len(ambiguous)}")
    if unmatched:
        print("\n=== 未匹配城市 (需人工定省) ===")
        for name, sub in unmatched:
            print(f"  {name:<10} {sub}")
    if ambiguous:
        print("\n=== 重名需复核 (GB 名在多个省存在) ===")
        for name, sub, gname, provs in ambiguous:
            print(f"  {name:<10} {sub:<14} {gname} -> 可能在省 {provs}")

    # 存中间结果
    mapping = {
        "matched": [{"name": m[0], "sub": m[1], "province": m[2], "city_code": m[3], "area_code": m[4], "gb_name": m[5]} for m in matched],
        "unmatched": [{"name": u[0], "sub": u[1]} for u in unmatched],
        "ambiguous": [{"name": a[0], "sub": a[1], "gb_name": a[2], "provinces": a[3]} for a in ambiguous],
        "hot": sorted(hot),
    }
    Path("/tmp/city_mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1))

    if "--write" in sys.argv:
        populate_db(mapping)


def populate_db(mapping):
    """把 provinces(34) 和 cities(673) 写入 DB."""
    from db.connection import get_db
    from db.schema import create_tables
    create_tables()
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── provinces: 大陆 31 + 港澳台 3 ──
    for p in gb_provinces:
        name = p["name"]
        conn.execute(
            "INSERT OR REPLACE INTO provinces (province_id, name, short_name, type) VALUES (?,?,?,?)",
            (p["code"], name, short_province(name), GB_PROVINCE_TYPE.get(name, "省")))
    for p in EXTRA_PROVINCES:
        conn.execute(
            "INSERT OR REPLACE INTO provinces (province_id, name, short_name, type) VALUES (?,?,?,?)",
            (p["code"], p["name"], short_province(p["name"]), p["type"]))
    print(f"provinces: {len(gb_provinces) + len(EXTRA_PROVINCES)}")

    # ── cities: 673 ──
    hot = set(mapping["hot"])
    n = 0
    for m in mapping["matched"]:
        name, sub, prov, ccode, acode, gname = (
            m["name"], m["sub"], m["province"], m["city_code"], m["area_code"], m["gb_name"])
        if sub in MUNICIPALITY:
            level = "province"
        elif acode:
            level = "county"
        else:
            level = "prefecture"
        conn.execute(
            """INSERT OR REPLACE INTO cities
               (city_id, name, province_id, gb_name, gb_city_code, gb_area_code, level, is_hot, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (sub, name, prov, gname, ccode, acode, level, 1 if name in hot else 0, now))
        n += 1
    conn.commit()
    conn.close()
    print(f"cities: {n}")

if __name__ == "__main__":
    main()
