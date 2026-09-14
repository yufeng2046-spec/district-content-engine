#!/usr/bin/env python3
"""
mark_cross_city.py — 给跨市盘打 is_cross_city 标记

背景: 各城"周边/zhoubian"商圈桶混入了异地社区(北京周边桶=保定/廊坊/秦皇岛/唐山/
威海/燕郊/烟台/张家口, 上海周边=嘉兴/苏州/南通/慈溪/湖州/昆山, 广州周边=东莞/佛山/
清远/肇庆/中山, 深圳周边=东莞/惠州, 成都周边=彭山/仁寿, 西安周边=咸阳)。LLM 写
"深圳探盘"若引用到东莞社区会串城市, 故需标记防误用。

规则(第一性原理, 可对抗验证):
  跨市 ⇔ communities.shangquan_id 挂在【专属 zhoubian 区】下、且商圈名为"别城市"的桶。
  - 专属 zhoubian 区 = shangquan_id 第 2 段 ∈ {beijingzhoubiana, chengduzhoubian,
    guangzhouzhoubian, shanghaizhoubian, shenzhenzhoubian, xianzhoubianc}
  - 排除 catch-all("其他"/"其它"桶: 不确定归属, 不标)
  - 同城"XX周边"桶(如 beijing_chaoyang_chaoyangzhoubian"朝阳周边")是正式区内边界,
    district 段非专属 zhoubian 区 → 不标。

用法: python3 mark_cross_city.py
对抗: python3 adversarial_test.py (如接入) / 本脚本自带 self-test
"""
import sys

from db.connection import get_db

# 专属 zhoubian district slug(shangquan_id 第 2 段)
ZHOU_BIAN_DISTRICTS = {
    "beijingzhoubiana", "chengduzhoubian", "guangzhouzhoubian",
    "shanghaizhoubian", "shenzhenzhoubian", "xianzhoubianc",
}
# catch-all 商圈名 → 不标
CATCH_ALL_NAMES = {"其他", "其它"}


def district_of(shangquan_id: str) -> str:
    parts = shangquan_id.split("_")
    return parts[1] if len(parts) >= 3 else ""


def load_cross_city_shangquan_ids(conn) -> set:
    """跨市商圈 id 集合: 专属 zhoubian 区下、非 catch-all 的桶。"""
    rows = conn.execute("SELECT shangquan_id, name FROM shangquans").fetchall()
    out = set()
    for sid, name in rows:
        if district_of(sid) in ZHOU_BIAN_DISTRICTS and name not in CATCH_ALL_NAMES:
            out.add(sid)
    return out


def main() -> int:
    conn = get_db()

    # 1. 迁移: 加 is_cross_city 列(幂等)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(communities)").fetchall()]
    if "is_cross_city" not in cols:
        conn.execute("ALTER TABLE communities ADD COLUMN is_cross_city INTEGER DEFAULT 0")
        print("✅ 新增列 is_cross_city")

    # 2. 计算跨市商圈集合
    cross = load_cross_city_shangquan_ids(conn)
    print(f"跨市商圈桶数: {len(cross)}")

    # 3. 标记(先清零再标, 保证幂等可重跑)
    conn.execute("UPDATE communities SET is_cross_city = 0")
    if cross:
        placeholders = ",".join("?" * len(cross))
        conn.execute(
            f"UPDATE communities SET is_cross_city = 1 WHERE shangquan_id IN ({placeholders})",
            tuple(cross),
        )
    conn.commit()

    # 4. 统计
    marked = conn.execute(
        "SELECT COUNT(*) FROM communities WHERE is_cross_city = 1"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM communities").fetchone()[0]
    print(f"标记跨市盘: {marked:,} / {total:,} ({marked / total * 100:.1f}%)")

    # 5. 自检(对抗)
    errs = self_test(conn, cross)
    conn.close()
    if errs:
        print(f"\n❌ 自检发现 {len(errs)} 个问题:")
        for e in errs:
            print(f"   - {e}")
        return 1
    print("\n✅ 自检全部通过")
    return 0


def self_test(conn, cross: set) -> list:
    errs = []

    # T1: 所有被标社区, 其 shangquan 必须在跨市桶集合里(无错标)
    bad = conn.execute("""
        SELECT COUNT(*) FROM communities
        WHERE is_cross_city = 1 AND shangquan_id IS NULL
    """).fetchone()[0]
    if bad:
        errs.append(f"有 {bad} 条 is_cross_city=1 但 shangquan_id 为 NULL")
    not_in_set = conn.execute("""
        SELECT COUNT(*) FROM communities
        WHERE is_cross_city = 1 AND shangquan_id NOT IN (SELECT shangquan_id FROM shangquans)
    """).fetchone()[0]
    if not_in_set:
        errs.append(f"有 {not_in_set} 条 is_cross_city=1 但 shangquan_id 不在跨市桶")

    # T2: 正式区(非 zhoubian district)的社区不得被标 —— 抽几个大区验证
    for dist in ["beijing_chaoyang", "shanghai_pudong", "shenzhen_nanshan"]:
        # 该正式区下有 shangquan 的社区是否误标
        cnt = conn.execute("""
            SELECT COUNT(*) FROM communities
            WHERE is_cross_city = 1 AND shangquan_id LIKE ?
        """, (dist + "_%",)).fetchone()[0]
        if cnt:
            errs.append(f"正式区 {dist} 有 {cnt} 条被误标为跨市")

    # T3: catch-all 桶(其他/其它)的社区不得被标
    catch = conn.execute("""
        SELECT COUNT(*) FROM communities c
        JOIN shangquans s ON c.shangquan_id = s.shangquan_id
        WHERE c.is_cross_city = 1 AND s.name IN ('其他','其它')
    """).fetchone()[0]
    if catch:
        errs.append(f"catch-all 桶有 {catch} 条被误标")

    # T4: 被标的社区必须有对应 shangquan 记录(引用完整)
    orphan_mark = conn.execute("""
        SELECT COUNT(*) FROM communities c
        LEFT JOIN shangquans s ON c.shangquan_id = s.shangquan_id
        WHERE c.is_cross_city = 1 AND s.shangquan_id IS NULL
    """).fetchone()[0]
    if orphan_mark:
        errs.append(f"有 {orphan_mark} 条 is_cross_city=1 但 shangquan 无记录")

    return errs


if __name__ == "__main__":
    sys.exit(main())
