#!/bin/bash
# Priority cleanup: 北京 → 燕郊/北三县 → 成都 → 西安
# Uses Beijing IP + VL captcha. Run AFTER current beijing_chaoyang finishes.
set -e
cd "$(dirname "$0")"

REGIONS=(
    "beijing_chaoyang"
    "beijing_haidian"
    "langfang_sanhe"
    "langfang_dachang"
    "langfang_xianghe"
    "chengdu_jinjiang"
    "chengdu_chenghua"
    "chengdu_jinniu"
    "chengdu_shuangliu"
    "chengdu_xindu"
    "chengdu_gaoxin"
    "chengdu_piduqu"
    "chengdu_wenjiang"
    "chengdu_qingyang"
    "chengdu_tainfuxinqu"
    "xa_gaoxinxa"
    "xa_lianhuqu"
    "xa_weiyangq"
    "xa_qujiangxinqu"
    "xa_jingkaiqux"
    "datong_pingcheng"
)

for region in "${REGIONS[@]}"; do
    echo ""
    echo "=============================================="
    echo "  Region: $region  |  $(date '+%H:%M:%S')"
    echo "=============================================="

    # For new cities (langfang_*), use listing+detail mode
    if [[ "$region" == langfang_* ]]; then
        PYTHONPATH=. python3 data/scrape_anjuke.py --region "$region" --max 250
    else
        MISSING=$(python3 -c "
from db.connection import get_db
conn = get_db()
cnt = conn.execute('SELECT COUNT(*) FROM communities WHERE region_id = ? AND detail_scraped_at IS NULL', ('$region',)).fetchone()[0]
conn.close()
print(cnt)
")
        if [ "$MISSING" = "0" ]; then
            echo "  No missing records, skipping"
            continue
        fi
        echo "  $MISSING records to scrape"
        PYTHONPATH=. python3 data/scrape_anjuke.py --region "$region" --details-only
    fi
    echo "  Done: $region ($(date '+%H:%M:%S'))"
done

echo ""
echo "=== Priority cleanup complete ==="
