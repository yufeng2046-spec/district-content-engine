#!/bin/bash
# run_b1_details.sh — B1 补详情链式 (shenzhen → guangzhou → shanghai)
# --details-only 天然增量: 成功爬取会写 detail_scraped_at, 重跑自动跳过已完成。
# 崩溃自动续跑 + 每次退出冷却 600s 防 IP 疲劳。
cd "$(dirname "$0")"

for region in shenzhen guangzhou shanghai; do
  while true; do
    remaining=$(PYTHONPATH=. python3 -c "
from db.connection import get_db
conn = get_db()
n = conn.execute('SELECT COUNT(*) FROM communities WHERE region_id=? AND detail_scraped_at IS NULL', ('$region',)).fetchone()[0]
print(n)
conn.close()
")
    echo "[$(date '+%F %T')] === $region 剩余缺详情: $remaining ==="
    if [ "$remaining" -eq 0 ]; then
      echo "[$(date '+%F %T')] === $region 全部完成 ==="
      break
    fi
    PYTHONPATH=. python3 data/scrape_anjuke.py --region "$region" --details-only --show \
      >> "/tmp/b1_${region}.log" 2>&1
    ec=$?
    echo "[$(date '+%F %T')] === $region 爬虫退出 (exit $ec), 冷却 600s ==="
    sleep 600
  done
  sleep 30
done
echo "[$(date '+%F %T')] === B1 补详情全部结束 ==="
