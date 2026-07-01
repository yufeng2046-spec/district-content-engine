"""Central config for district-content-engine."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "district_content.db"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
SCRIPTS_DIR = BASE_DIR / "scripts"

# Region config
REGION_ID = "xianyang_yangling"
REGION_NAME = "杨陵区"
CITY_NAME = "咸阳"
PROVINCE = "陕西"

# Gaode API — set via env var GAODE_KEY
# Get a free key at https://lbs.amap.com
import os
GAODE_KEY = os.getenv("GAODE_KEY", "")

# DeepSeek API — set via env var DEEPSEEK_KEY
# Get a key at https://platform.deepseek.com
DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY", "")
DEEPSEEK_MODEL = "deepseek/deepseek-chat"

# Milvus (shared with competitor-report)
MILVUS_URI = "http://localhost:19530"
EMBED_URL = "http://localhost:8011/embed"
MILVUS_COLLECTION = "real_estate_knowledge"

# Douyin search keywords for Yangling
DOUYIN_KEYWORDS = [
    "杨凌买房", "杨凌房产", "杨凌新房", "杨凌二手房",
    "杨陵区买房", "杨陵区房产", "杨陵区新房", "杨陵区二手房",
]

# Anjuke
ANJUKE_YANGLING_URL = "https://xianyang.anjuke.com/community/yangling/"

# Scraper settings (calibrated per open-source Anjuke crawlers for anti-bot)
PAGE_DELAY_MIN_MS = 2_000   # Min delay between page loads
PAGE_DELAY_MAX_MS = 4_000   # Max delay between page loads
DETAIL_DELAY_MIN_MS = 3_000  # Min delay between detail pages
DETAIL_DELAY_MAX_MS = 5_000  # Max delay between detail pages
RPM_SOFT_CAP = 4             # Soft rate limit: requests per minute
RPM_HARD_CAP = 6             # Hard rate limit
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
