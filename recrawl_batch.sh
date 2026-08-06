#!/bin/bash
# 商圈精确重爬 — 成都 12 偏斜区 + 西安碑林
# 用法: bash recrawl_batch.sh    (nohup 后台跑)
# 每区 --shangquan all --listings-only --xvfb, 无人值守, 验证码自动跳过
set -u
cd "$(dirname "$0")"

REGIONS=(
  chengdu_xindu
  chengdu_chongzhoushi
  chengdu_dujiangyan
  chengdu_wenjiang
  chengdu_pengzhoushi
  chengdu_qingbaijiangqu
  chengdu_jintangxian
  chengdu_dayixian
  chengdu_xinjinxian
  chengdu_chengduzhoubian
  chengdu_qionglaishi
  chengdu_cdjianyang
  xa_beilinqu
)

echo "=== 批量重爬开始 $(date) ==="
for region in "${REGIONS[@]}"; do
  echo
  echo "========== $(date '+%m-%d %H:%M') START $region =========="
  PYTHONPATH=. python3 data/scrape_anjuke.py \
    --region "$region" --shangquan all --listings-only --xvfb \
    >> "/tmp/recrawl_${region}.log" 2>&1
  echo "========== $(date '+%m-%d %H:%M') DONE $region (exit $?) =========="
done
echo "=== 全部完成 $(date) ==="
