#!/bin/bash
# run_b4_chain.sh — B4 按商圈重爬链式接力 (shenzhen→guangzhou→shanghai)
# 用法: ./run_b4_chain.sh   (nohup 后台运行)
# 每城完成后自动进入下一城; 全程 log 分别写 /tmp/b4_{city}.log
cd "$(dirname "$0")"

for city in shenzhen guangzhou shanghai; do
  echo "[$(date '+%F %T')] === B4 开始: $city ==="
  PYTHONPATH=. python3 data/scrape_anjuke.py --region "$city" --shangquan all --listings-only --show \
    >> "/tmp/b4_$city.log" 2>&1
  echo "[$(date '+%F %T')] === B4 结束: $city (exit $?) ==="
  # 城间停顿, 避免立刻切换触发风控
  sleep 30
done
echo "[$(date '+%F %T')] === B4 三城全部结束 ==="
