#!/usr/bin/env python3
"""数据完整性校验 — 防止跨城 shangquan_id 等历史 bug 复发。

用法:
    python3 validate_shangquan.py          # 全部检查
    python3 validate_shangquan.py --fast   # 只查跨城 + 孤儿 (跑得快)

检查项:
  C1. 跨城 shangquan_id (shangquan 城市 ≠ 小区 city_id)   ← Bug1 根因
  C2. 孤儿 shangquan_id (不在 shangquans 表)
  C3. communities.region_id → districts 可 join (区级一致性)  ← Bug2
  C4. shangquans.district_id → districts 可 join
  C5. communities 无省/无城市 (回填完整性)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db.connection import get_db


def main():
    fast = "--fast" in sys.argv
    conn = get_db()
    ok = True

    def report(name, bad, detail=""):
        nonlocal ok
        status = "✅" if bad == 0 else "❌"
        print(f"  {status} {name}: {bad:,}")
        if bad and detail:
            print(f"      {detail}")

    print("═" * 50)
    print("数据完整性校验")
    print("═" * 50)

    # C1: 跨城 shangquan_id
    bad = conn.execute("""
        SELECT COUNT(*) FROM communities
        WHERE city_id IS NOT NULL AND shangquan_id IS NOT NULL
          AND substr(shangquan_id,1,instr(shangquan_id||'_','_')-1) != city_id
    """).fetchone()[0]
    if bad:
        detail = conn.execute("""
            SELECT c.region_id, c.shangquan_id, COUNT(*) FROM communities c
            WHERE c.city_id IS NOT NULL AND c.shangquan_id IS NOT NULL
              AND substr(c.shangquan_id,1,instr(c.shangquan_id||'_','_')-1) != c.city_id
            GROUP BY 1,2 ORDER BY 3 DESC LIMIT 3
        """).fetchall()
        detail = "例: " + ", ".join(f"{r[0]}→{r[1]}" for r in detail)
    else:
        detail = ""
    report("C1 跨城 shangquan_id", bad, detail)

    # C2: 孤儿 shangquan_id
    bad = conn.execute("""
        SELECT COUNT(*) FROM communities c
        LEFT JOIN shangquans s ON c.shangquan_id = s.shangquan_id
        WHERE c.shangquan_id IS NOT NULL AND s.shangquan_id IS NULL
    """).fetchone()[0]
    report("C2 孤儿 shangquan_id", bad)

    if fast:
        conn.close()
        print("\n" + ("✅ 全部通过" if ok else "❌ 存在问题"))
        sys.exit(0 if ok else 1)

    # C3: communities.region_id → districts
    bad = conn.execute("""
        SELECT COUNT(DISTINCT c.region_id) FROM communities c
        LEFT JOIN districts d ON d.district_id = c.region_id
        WHERE d.district_id IS NULL AND c.region_id NOT IN ('shanghai','shenzhen','guangzhou','yangling')
    """).fetchone()[0]
    report("C3 region_id 无法 join districts", bad)

    # C4: shangquans.district_id → districts
    bad = conn.execute("""
        SELECT COUNT(*) FROM shangquans s
        LEFT JOIN districts d ON s.district_id = d.district_id
        WHERE d.district_id IS NULL
    """).fetchone()[0]
    report("C4 shangquans.district_id 孤儿", bad)

    # C5: communities 无省/无城市
    bad = conn.execute("SELECT COUNT(*) FROM communities WHERE province_id IS NULL OR city_id IS NULL").fetchone()[0]
    report("C5 communities 缺省/市", bad)

    # 附: 覆盖率总览
    t = conn.execute("SELECT COUNT(*) FROM communities").fetchone()[0]
    null_sq = conn.execute("SELECT COUNT(*) FROM communities WHERE shangquan_id IS NULL").fetchone()[0]
    print(f"\n  小区总数 {t:,} | NULL 商圈 {null_sq:,} ({null_sq/t*100:.1f}%)")
    conn.close()

    print("\n" + ("✅ 全部通过" if ok else "❌ 存在问题"))


if __name__ == "__main__":
    main()
