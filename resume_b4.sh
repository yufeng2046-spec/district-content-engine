#!/bin/bash
# resume_b4.sh — B4 按商圈重跑健壮续跑 (guangzhou → shanghai)
# 每城循环: 直到 progress 完成数 == 该城商圈总数 才进入下一城。
# 崩溃(TargetClosedError等)自动从断点续跑, 无需人工干预。
cd "$(dirname "$0")"

# 与爬虫逻辑一致的商圈总数统计 (city-level region → 全部 district)
count_total() {
  python3 -c "
import json, sys
city = '$1'
sq = json.load(open(f'data/shangquan_{city}.json'))
n = 0
for dn, di in sq.get('districts', {}).items():
    n += len(di.get('shangquan', []))
print(n)
"
}

count_done() {
  python3 -c "
import json, sys
city = '$1'
try:
    d = json.load(open(f'data/progress_{city}.json'))
    print(len(d.get('completed', [])))
except Exception:
    print(0)
"
}

for city in guangzhou shanghai; do
  total=$(count_total "$city")
  while true; do
    done=$(count_done "$city")
    echo "[$(date '+%F %T')] === $city: 已完成 $done/$total 商圈 ==="
    if [ "$done" -ge "$total" ]; then
      echo "[$(date '+%F %T')] === $city 全部完成 ==="
      break
    fi
    PYTHONPATH=. python3 data/scrape_anjuke.py --region "$city" --shangquan all --listings-only --show \
      >> "/tmp/b4_${city}.log" 2>&1
    ec=$?
    # IP 冷却: 每次爬虫退出后等 10 分钟再重试, 避免验证码墙死循环加剧 IP 疲劳
    # (README: 30-60min 冷却显著降低验证码频率; 无人值守时 10min/次足够)
    echo "[$(date '+%F %T')] === $city 爬虫退出 (exit $ec), 冷却 600s 后重试 ==="
    sleep 600
  done
  sleep 30
done
echo "[$(date '+%F %T')] === 续跑全部结束 ==="
