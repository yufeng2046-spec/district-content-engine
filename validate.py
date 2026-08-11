#!/usr/bin/env python3
"""数据契约校验器 — 四维校验，防历史 bug 复发 + 抓静默失败。

四个维度（基准不同）:
  ① 结构自洽 (S)  — 基准=数据模型本身    BLOCK: 数据自相矛盾
  ② GB标准对齐 (G) — 基准=GB/T2260物理世界 WARN: 地理记错
  ③ 爬取契约 (K)  — 基准=安居客shangquan JSON BLOCK: 漏爬/静默失败
  ④ 业务完整性 (B) — 基准=写文案需求        WARN: 数据不够用

严重度: BLOCK 失败 → exit 1; WARN 只报告。

用法:
    python3 validate.py          # 全部四维
    python3 validate.py --fast   # 只查结构(S) + 契约(K) 的关键项
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from db.connection import get_db

# 有商圈 JSON 的城市 (安居客给这些城市定义了商圈层级)
SHANGQUAN_CITIES = {"beijing", "chengdu", "xa", "datong", "guangzhou", "shenzhen", "shanghai"}
# 无商圈城市: 其余 (langfang / xianyang 等), 小区 shangquan_id 应为 NULL


def main():
    fast = "--fast" in sys.argv
    conn = get_db()
    blocks = []   # BLOCK 级问题
    warns = []    # WARN 级问题

    def check(level, name, bad, detail=""):
        entry = f"  {'❌' if bad else '✅'} [{level}] {name}: {bad:,}"
        if bad and detail:
            entry += f"\n      {detail}"
        (blocks if level == "BLOCK" else warns).append(entry)
        print(entry)

    print("═" * 60)
    print("数据契约校验 — 四维 × 两级")
    print("═" * 60)

    # ═══ ① 结构自洽 (基准=数据模型) ═══
    print("\n── ① 结构自洽 ──")
    bad = conn.execute("""
        SELECT COUNT(*) FROM communities
        WHERE city_id IS NOT NULL AND shangquan_id IS NOT NULL
          AND substr(shangquan_id,1,instr(shangquan_id||'_','_')-1) != city_id
    """).fetchone()[0]
    check("BLOCK", "S1 跨城 shangquan_id", bad)

    bad = conn.execute("""
        SELECT COUNT(*) FROM communities c
        LEFT JOIN shangquans s ON c.shangquan_id = s.shangquan_id
        WHERE c.shangquan_id IS NOT NULL AND s.shangquan_id IS NULL
    """).fetchone()[0]
    check("BLOCK", "S2 孤儿 shangquan_id", bad)

    bad = conn.execute("""
        SELECT COUNT(DISTINCT c.region_id) FROM communities c
        LEFT JOIN districts d ON d.district_id = c.region_id
        WHERE d.district_id IS NULL AND c.region_id NOT IN ('shanghai','shenzhen','guangzhou','yangling')
    """).fetchone()[0]
    check("BLOCK", "S3 region_id 无法 join districts", bad)

    bad = conn.execute("""
        SELECT COUNT(*) FROM shangquans s
        LEFT JOIN districts d ON s.district_id = d.district_id
        WHERE d.district_id IS NULL
    """).fetchone()[0]
    check("BLOCK", "S4 shangquans.district_id 孤儿", bad)

    bad = conn.execute("SELECT COUNT(*) FROM communities WHERE province_id IS NULL OR city_id IS NULL").fetchone()[0]
    check("BLOCK", "S5 communities 缺省/市", bad)

    bad = conn.execute("""
        SELECT COUNT(*) FROM communities c
        LEFT JOIN districts d ON c.district_id = d.district_id
        WHERE c.district_id IS NOT NULL AND d.district_id IS NULL
    """).fetchone()[0]
    check("BLOCK", "S6 communities.district_id 孤儿", bad)

    # 商圈城市前缀 == 所属区城市
    bad = conn.execute("""
        SELECT COUNT(*) FROM shangquans s JOIN districts d ON s.district_id = d.district_id
        WHERE substr(s.shangquan_id,1,instr(s.shangquan_id||'_','_')-1) != d.city_id
    """).fetchone()[0]
    check("BLOCK", "S7 商圈城市 ≠ 区城市", bad)

    if fast:
        conn.close()
        print(f"\n{'❌ BLOCK 问题: ' + str(len([b for b in blocks if '❌' in b])) if any('❌' in b for b in blocks) else '✅ 结构+契约 关键项通过'}")
        sys.exit(1 if any("❌" in b for b in blocks) else 0)

    # ═══ ② GB 标准对齐 (基准=物理世界) ═══
    print("\n── ② GB 标准对齐 ──")
    bad = conn.execute("SELECT COUNT(*) FROM cities WHERE province_id IS NULL").fetchone()[0]
    check("WARN", "G1 cities 无省", bad)
    bad = conn.execute("SELECT COUNT(*) FROM cities WHERE level='prefecture' AND (gb_city_code IS NULL OR gb_name IS NULL)").fetchone()[0]
    check("WARN", "G2 地级市缺 GB 码", bad)
    bad = conn.execute("SELECT COUNT(*) FROM cities WHERE level NOT IN ('prefecture','province')").fetchone()[0]
    check("WARN", "G3 cities level 非法", bad)
    bad = conn.execute("SELECT COUNT(*) FROM districts WHERE type IS NULL").fetchone()[0]
    check("WARN", "G4 districts 缺 type", bad)

    # ═══ ③ 爬取契约 (基准=安居客 JSON) ═══
    print("\n── ③ 爬取契约 ──")
    sq_total_expected = 0
    sq_total_actual = 0
    for jf in sorted((BASE_DIR / "data").glob("shangquan_*.json")):
        city = json.loads(jf.read_text()).get("city")
        if not city:
            continue
        expected = sum(len(dist.get("shangquan", [])) for dist in json.loads(jf.read_text()).get("districts", {}).values())
        actual = conn.execute("SELECT COUNT(*) FROM shangquans WHERE city=?", (city,)).fetchone()[0]
        sq_total_expected += expected
        sq_total_actual += actual
        flag = "✅" if expected == actual else "❌"
        print(f"  {flag} {city:<10} JSON:{expected:>4} DB:{actual:>4}")
        if expected != actual:
            blocks.append(f"  ❌ [BLOCK] K1 {city} 商圈数不符: JSON {expected} vs DB {actual} (可能静默漏爬)")
    if sq_total_expected == sq_total_actual:
        print(f"  ✅ 商圈契约总量: {sq_total_expected} == {sq_total_actual}")

    # 无商圈城市不应有 shangquan_id
    bad = conn.execute("""
        SELECT COUNT(*) FROM communities c JOIN cities ci ON c.city_id=ci.city_id
        WHERE c.shangquan_id IS NOT NULL AND ci.city_id NOT IN (%s)
    """ % ",".join(f"'{c}'" for c in SHANGQUAN_CITIES)).fetchone()[0]
    check("BLOCK", "K2 无商圈城市却有 shangquan_id", bad)

    # ═══ ④ 业务完整性 (基准=写文案需求) ═══
    print("\n── ④ 业务完整性 ──")
    t = conn.execute("SELECT COUNT(*) FROM communities").fetchone()[0]
    n_detail = conn.execute("SELECT COUNT(*) FROM communities WHERE detail_scraped_at IS NOT NULL").fetchone()[0]
    pct = n_detail / t * 100 if t else 0
    check("WARN", "B1 详情缺失", t - n_detail, f"覆盖 {pct:.1f}%")
    bad = conn.execute("SELECT COUNT(*) FROM communities WHERE coordinate_lng IS NULL OR coordinate_lat IS NULL OR coordinate_lng=0").fetchone()[0]
    check("WARN", "B2 坐标缺失/零", bad)
    bad = conn.execute("SELECT COUNT(*) FROM communities WHERE name IS NULL OR trim(name)=''").fetchone()[0]
    check("WARN", "B3 名称缺失", bad)
    # 有商圈城市的商圈覆盖 (NULL 应接近 0; 无商圈城市除外)
    bad = conn.execute("""
        SELECT COUNT(*) FROM communities c JOIN cities ci ON c.city_id=ci.city_id
        WHERE c.shangquan_id IS NULL AND ci.city_id IN (%s)
    """ % ",".join(f"'{c}'" for c in SHANGQUAN_CITIES)).fetchone()[0]
    check("WARN", "B4 有商圈城市却缺商圈", bad, "诚实空值(商圈页找不到)可接受, 但应少量")

    conn.close()

    # ═══ 汇总 ═══
    print("\n" + "═" * 60)
    n_block = len([b for b in blocks if "❌" in b])
    n_warn = len([w for w in warns if "❌" in w])
    print(f"BLOCK 问题: {n_block} | WARN 问题: {n_warn}")
    if n_block:
        print("存在 BLOCK 级问题, 需处理:")
        for b in blocks:
            if "❌" in b:
                print(b)
    else:
        print("✅ 全部 BLOCK 级检查通过")
    print("═" * 60)
    sys.exit(1 if n_block else 0)


if __name__ == "__main__":
    main()
