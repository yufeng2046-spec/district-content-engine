#!/usr/bin/env python3
"""对抗性检查 — 注入 bug 验证校验器能抓到, 且干净数据不误报。

对 validate.py 和 check_crawl.py 做注入测试:
  T1. 跨城 shangquan     → validate S1 应 BLOCK
  T2. 孤儿 shangquan     → validate S2 应 BLOCK
  T3. 缺省/市            → validate S5 应 BLOCK
  T4. 孤儿 district      → validate S6 应 BLOCK
  T5. 商圈城市≠区城市     → validate S7 应 BLOCK
  T6. 无商圈城市有商圈     → validate K2 应 BLOCK
  T7. datong类静默失败   → check_crawl 应 BLOCK
  T8. 干净数据           → 两者应通过 (无 BLOCK)
"""
from __future__ import annotations
import pathlib
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

TEST_DB = pathlib.Path("/tmp/test_validate.db")


def make_copy():
    src = sqlite3.connect(str(pathlib.Path(__file__).resolve().parent / "district_content.db"))
    dst = sqlite3.connect(str(TEST_DB))
    src.backup(dst)
    dst.close()
    src.close()


def run_validator(inject: str | None = None) -> int:
    """在测试库上注入+跑 validate.py, 返回退出码."""
    import db.connection as dc
    dc.DB_PATH = TEST_DB
    if inject:
        c = dc.get_db()
        c.execute(inject)
        c.commit()
        c.close()
    import validate
    try:
        validate.main()
        return 0
    except SystemExit as e:
        return e.code


def run_checkcrawl(inject: str | None = None, region: str = "") -> int:
    import db.connection as dc
    dc.DB_PATH = TEST_DB
    if inject:
        c = dc.get_db()
        c.execute(inject)
        c.commit()
        c.close()
    import check_crawl
    argv_backup = sys.argv
    sys.argv = ["check_crawl.py"] + (["--region", region] if region else [])
    try:
        check_crawl.main()
        return 0
    except SystemExit as e:
        return e.code
    finally:
        sys.argv = argv_backup


def main():
    results = []

    # ═══ T1: 跨城 shangquan (真实存在的外市商圈) ═══
    make_copy()
    code = run_validator(
        "UPDATE communities SET shangquan_id='shanghai_pudong_sanlinsh' "
        "WHERE community_id IN (SELECT community_id FROM communities WHERE city_id='chengdu' LIMIT 1)")
    results.append(("T1 跨城shangquan→S1", code == 1))

    # ═══ T2: 孤儿 shangquan ═══
    make_copy()
    code = run_validator(
        "UPDATE communities SET shangquan_id='fake_city_fake_sq' "
        "WHERE community_id IN (SELECT community_id FROM communities WHERE shangquan_id IS NOT NULL LIMIT 1)")
    results.append(("T2 孤儿shangquan→S2", code == 1))

    # ═══ T3: 缺省/市 ═══
    make_copy()
    code = run_validator(
        "UPDATE communities SET province_id=NULL WHERE community_id IN (SELECT community_id FROM communities LIMIT 1)")
    results.append(("T3 缺省/市→S5", code == 1))

    # ═══ T4: 孤儿 district_id ═══
    make_copy()
    code = run_validator(
        "UPDATE communities SET district_id='fake_district' "
        "WHERE community_id IN (SELECT community_id FROM communities WHERE district_id IS NOT NULL LIMIT 1)")
    results.append(("T4 孤儿district→S6", code == 1))

    # ═══ T5: 商圈城市≠区城市 ═══
    make_copy()
    code = run_validator(
        "UPDATE shangquans SET shangquan_id='shanghai_bad_sq' WHERE shangquan_id LIKE 'chengdu_%' LIMIT 1")
    results.append(("T5 商圈城市≠区城市→S7", code == 1))

    # ═══ T6: 无商圈城市(廊坊)有 shangquan ═══
    make_copy()
    code = run_validator(
        "UPDATE communities SET shangquan_id='chengdu_wuhou_cjljwhq' WHERE region_id='langfang_dachang' LIMIT 1")
    results.append(("T6 无商圈城市有商圈→K2", code == 1))

    # ═══ T7: datong 类静默失败 (删光该区商圈) ═══
    make_copy()
    code = run_checkcrawl("DELETE FROM shangquans WHERE district_id='datong_pingcheng'", region="datong_pingcheng")
    results.append(("T7 datong类静默失败→check_crawl BLOCK", code == 1))

    # ═══ T8: 干净数据 → 无 BLOCK ═══
    make_copy()
    code = run_validator()
    results.append(("T8 干净数据→validate 无BLOCK", code == 0))
    make_copy()
    code = run_checkcrawl()
    results.append(("T8 干净数据→check_crawl 无BLOCK", code == 0))

    # ═══ 汇总 ═══
    print("\n" + "═" * 60)
    print("对抗性检查结果")
    print("═" * 60)
    all_pass = True
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
        if not ok:
            all_pass = False
    print("═" * 60)
    print("✅ 全部通过 — 校验器能抓注入 bug, 干净数据不误报" if all_pass else "❌ 有失败")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
