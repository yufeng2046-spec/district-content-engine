#!/usr/bin/env python3
"""
fix_district_type.py — 回填 districts.type (G4 校验清零)

背景: districts 表的 type 列由 migrate_add_districts.py 添加但从未填充，
validate.py G4 报 "districts 缺 type: 118"（全表 118 行）。

type 分类依据中国行政区划（GB/T 2260）：
  - 市辖区：正式市辖区
  - 县：县
  - 县级市：县级市
  - 自治县：自治县（大厂回族自治县）
  - 功能区：非行政区划的功能区（高新区/经开区/各类新区/布吉街道等）
  - 其他：爬取用的"XX周边"伪桶

用法: python3 fix_district_type.py
"""
import sys

from db.connection import get_db

# slug -> type (键用 slug；districts.district_id 由 {city}_{slug} 组成)
TYPE_MAP = {
    # ── beijing: 17 区全部市辖区 ──
    "chaoyang": "市辖区", "haidian": "市辖区", "changping": "市辖区",
    "fengtai": "市辖区", "daxing": "市辖区", "tongzhou": "市辖区",
    "fangshan": "市辖区", "shunyi": "市辖区", "xicheng": "市辖区",
    "dongchenga": "市辖区", "miyun": "市辖区", "shijingshan": "市辖区",
    "huairou": "市辖区", "mentougou": "市辖区", "yanqing": "市辖区",
    "pinggua": "市辖区",
    "beijingzhoubiana": "其他",  # 北京周边（伪桶）

    # ── chengdu: 25 ──
    "chenghua": "市辖区", "jinjiang": "市辖区", "jinniu": "市辖区",
    "longquanyi": "市辖区", "piduqu": "市辖区", "qingbaijiangqu": "市辖区",
    "qingyang": "市辖区", "shuangliu": "市辖区", "wenjiang": "市辖区",
    "wuhou": "市辖区", "xindu": "市辖区",
    "cdjianyang": "县级市", "chongzhoushi": "县级市", "dujiangyan": "县级市",
    "pengzhoushi": "县级市", "qionglaishi": "县级市",
    "cdpujiangxian": "县", "dayixian": "县", "jintangxian": "县",
    "xinjinxian": "县",
    "gaoxin": "功能区", "gaoxinxiqu": "功能区", "tainfuxinqu": "功能区",
    "dongbuxinqu": "功能区",
    "chengduzhoubian": "其他",  # 成都周边

    # ── datong: 10 ──
    "pingcheng": "市辖区", "yunganga": "市辖区", "yunzhoud": "市辖区",
    "xinrong": "市辖区",
    "yanggao": "县", "hunyuan": "县", "lingqiu": "县",
    "tianzhen": "县", "zuoyun": "县", "guangling": "县",

    # ── guangzhou: 12 (增城/从化已撤市设区) ──
    "baiyun": "市辖区", "conghua": "市辖区", "fanyu": "市辖区",
    "haizhu": "市辖区", "huadu": "市辖区", "huangpua": "市辖区",
    "liwan": "市辖区", "nansha": "市辖区", "tianhe": "市辖区",
    "yuexiu": "市辖区", "zengcheng": "市辖区",
    "guangzhouzhoubian": "其他",  # 广州周边

    # ── langfang: 3 ──
    "dachang": "自治县",  # 大厂回族自治县
    "sanhe": "县级市",    # 三河市
    "xianghe": "县",      # 香河县

    # ── shanghai: 17 ──
    "baoshan": "市辖区", "changning": "市辖区", "chongming": "市辖区",
    "fengxian": "市辖区", "hongkou": "市辖区", "huangpu": "市辖区",
    "jiading": "市辖区", "jingan": "市辖区", "jinshan": "市辖区",
    "minhang": "市辖区", "pudong": "市辖区", "putuo": "市辖区",
    "qingpu": "市辖区", "songjiang": "市辖区", "xuhui": "市辖区",
    "yangpu": "市辖区",
    "shanghaizhoubian": "其他",  # 上海周边

    # ── shenzhen: 12 ──
    "baoan": "市辖区", "futian": "市辖区", "longgang": "市辖区",
    "longhuaq": "市辖区", "luohu": "市辖区", "nanshan": "市辖区",
    "pingshanq": "市辖区", "yantian": "市辖区", "guangmingx": "市辖区",
    "dapengxinqu": "功能区",  # 大鹏新区（功能区）
    "bujisz": "功能区",       # 布吉（龙岗区下辖街道，anjuke 当区爬）
    "shenzhenzhoubian": "其他",  # 深圳周边

    # ── xa: 21 ──
    "baqiaoqu": "市辖区", "beilinqu": "市辖区", "changanb": "市辖区",
    "huyiqu": "市辖区", "lianhuqu": "市辖区", "lintongqu": "市辖区",
    "weiyangq": "市辖区", "xinchengqu": "市辖区", "yantaqu": "市辖区",
    "yanliangqu": "市辖区", "gaoling": "市辖区",
    "lantianxian": "县", "zhouzhixian": "县",
    "chanba": "功能区", "daxingxinqu": "功能区", "gaoxinxa": "功能区",
    "gjgwqxa": "功能区", "jingkaiqux": "功能区", "qujiangxinqu": "功能区",
    "xixianxinqu": "功能区",
    "xianzhoubianc": "其他",  # 西安周边

    # ── yangling: 1 ──
    "yangling": "市辖区",  # 杨陵区（咸阳市）
}


def main() -> int:
    conn = get_db()
    rows = conn.execute(
        "SELECT district_id, slug FROM districts WHERE type IS NULL"
    ).fetchall()
    print(f"待回填 districts: {len(rows)}")

    missing = [r for r in rows if r[1] not in TYPE_MAP]
    if missing:
        print("❌ 以下 slug 无映射，请补充 TYPE_MAP:")
        for _, slug in missing:
            print(f"   {slug}")
        conn.close()
        return 1

    updated = 0
    for dist_id, slug in rows:
        t = TYPE_MAP[slug]
        conn.execute("UPDATE districts SET type=? WHERE district_id=?", (t, dist_id))
        updated += 1
    conn.commit()

    # 校验清零
    left = conn.execute(
        "SELECT COUNT(*) FROM districts WHERE type IS NULL"
    ).fetchone()[0]
    by_type = conn.execute(
        "SELECT type, COUNT(*) FROM districts GROUP BY type ORDER BY 2 DESC"
    ).fetchall()
    print(f"✅ 已回填 {updated}，剩余 NULL: {left}")
    for t, c in by_type:
        print(f"   {t}: {c}")
    conn.close()
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
