#!/bin/bash
# run_fixjson.sh — 历史存量 property_basic/interpretation 回填链式 (--fix-json)
# 只 UPDATE 两列, 零数据丢失; 逐 region 循环到 0 为止; 崩溃自动续跑 + 600s IP 冷却。
# 顺序: 先正常区(主城), 后跨市 zhoubian 桶(已标 is_cross_city, 优先级低)。
cd "$(dirname "$0")"

# 目标 regions = 缺 property_basic 且有详情的社区所在 region, zhoubian 排最后
get_targets() {
  PYTHONPATH=. python3 -c "
from db.connection import get_db
conn = get_db()
rows = conn.execute('''SELECT region_id FROM communities
    WHERE detail_scraped_at IS NOT NULL AND (property_basic_json IS NULL OR property_basic_json='')
    GROUP BY region_id''').fetchall()
regions = [r[0] for r in rows]
# zhoubian/周边 桶排最后
def key(r):
    return (1 if ('zhoubian' in r or 'zhoubiana' in r or 'zhoubianc' in r) else 0, r)
for r in sorted(regions, key=key):
    print(r)
conn.close()
"
}

for region in $(get_targets); do
  prev=999999999
  strikes=0
  while true; do
    remaining=$(PYTHONPATH=. python3 -c "
from data.scrape_anjuke import load_communities_missing_json
print(len(load_communities_missing_json('$region')))
")
    echo "[$(date '+%F %T')] === $region 剩余缺 property_basic: $remaining ==="
    if [ "$remaining" -eq 0 ]; then
      echo "[$(date '+%F %T')] === $region 全部完成 ==="
      break
    fi
    # 无进展保护: 连续 3 轮不下降 → 疑似页面本就无数据(新房/自建房), 跳过该 region
    if [ "$remaining" -ge "$prev" ]; then
      strikes=$((strikes + 1))
      if [ "$strikes" -ge 2 ]; then
        echo "[$(date '+%F %T')] === $region 停滞(剩 $remaining, 连续 $strikes 轮无进展), 跳过 ==="
        break
      fi
    else
      strikes=0
    fi
    prev=$remaining
    PYTHONPATH=. python3 data/scrape_anjuke.py --region "$region" --fix-json --show \
      >> "/tmp/fixjson_${region}.log" 2>&1
    ec=$?
    echo "[$(date '+%F %T')] === $region 爬虫退出 (exit $ec), 冷却 600s ==="
    sleep 600
  done
  sleep 20
done
echo "[$(date '+%F %T')] === fix-json 全量回填结束 ==="
