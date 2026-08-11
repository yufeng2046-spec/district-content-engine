#!/usr/bin/env python3
"""部分失败检测 — 自动对比「预期 vs 实际」，抓 datong 类静默失败。

背景: datong bug — 脚本跑完(看起来成功)但 0 商圈 (区匹配失败)。这种"部分失败"
不主动对比预期是发现不了的。

对比项 (基准=安居客 shangquan JSON):
  E1. 每个区: JSON 预期商圈数 vs DB 实际商圈数  → 不符=漏爬/匹配失败
  E2. 每个区: 预期商圈>0 但实际=0  → BLOCK (datong 类)
  E3. 每个区: 小区量级 (预期商圈数×25 下限 vs 实际小区数) → 明显偏少=警告

用法:
    python3 check_crawl.py                  # 全量扫描
    python3 check_crawl.py --region chengdu_wuhou  # 只查一个区
退出码: 有 BLOCK 问题 → 1; 否则 0
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from db.connection import get_db


def main():
    region_filter = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--region" and i + 1 < len(args):
            region_filter = args[i + 1]

    conn = get_db()
    problems = []
    print("═" * 60)
    print("部分失败检测 — 预期 vs 实际")
    print("═" * 60)

    for jf in sorted((BASE_DIR / "data").glob("shangquan_*.json")):
        data = json.loads(jf.read_text())
        city = data.get("city")
        for dist_key, dist_info in data.get("districts", {}).items():
            dist_slug = dist_info.get("slug") or dist_key
            district_id = f"{city}_{dist_slug}"
            if region_filter and district_id != region_filter:
                continue

            expected_sq = len(dist_info.get("shangquan", []))
            actual_sq = conn.execute(
                "SELECT COUNT(*) FROM shangquans WHERE district_id=?", (district_id,)).fetchone()[0]
            actual_comm = conn.execute(
                "SELECT COUNT(*) FROM communities WHERE region_id=?", (district_id,)).fetchone()[0]

            # E2: 预期>0 但实际商圈=0 → BLOCK (匹配失败/静默漏爬)
            if expected_sq > 0 and actual_sq == 0:
                problems.append(f"❌ [BLOCK] {district_id}: JSON 预期 {expected_sq} 商圈, DB 实际 0 → 区匹配/爬取失败!")
            # E1: 商圈数不符 → WARN
            elif expected_sq != actual_sq:
                problems.append(f"⚠️ [WARN] {district_id}: 预期 {expected_sq} 商圈, 实际 {actual_sq}")
            # E3: 小区量级明显偏少 (预期商圈×25 下限)
            min_expected_comm = expected_sq * 25
            if expected_sq > 0 and actual_comm > 0 and actual_comm < min_expected_comm * 0.3:
                problems.append(f"⚠️ [WARN] {district_id}: 小区 {actual_comm} 明显偏少 (预期≥{min_expected_comm})")

    if not region_filter:
        # 全量时也对比: 无商圈 JSON 的城市不该有商圈表数据
        sq_cities = {json.loads(p.read_text()).get("city") for p in (BASE_DIR / "data").glob("shangquan_*.json")}
        for row in conn.execute("SELECT DISTINCT city FROM shangquans").fetchall():
            if row["city"] not in sq_cities:
                problems.append(f"⚠️ [WARN] 城市 {row['city']} 有商圈数据但无 JSON (异常)")

    conn.close()

    print("\n" + "═" * 60)
    if problems:
        print(f"发现问题 {len(problems)}:")
        for p in problems:
            print(f"  {p}")
        has_block = any("BLOCK" in p for p in problems)
        print(f"\n{'❌ 有 BLOCK 级问题' if has_block else '⚠️ 仅警告'}")
        sys.exit(1 if has_block else 0)
    else:
        print("✅ 预期 vs 实际 全部一致")
        sys.exit(0)


if __name__ == "__main__":
    main()
