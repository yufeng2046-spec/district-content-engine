"""Database schema — multi-region edition."""

from db.connection import get_db


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchall()
    return len(rows) > 0


def create_tables() -> None:
    conn = get_db()

    # ── Core tables ────────────────────────────────────────────

    conn.execute("""
        CREATE TABLE IF NOT EXISTS communities (
            community_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT,
            year_built INTEGER,
            developer TEXT,
            property_mgmt TEXT,
            property_fee REAL,
            floor_area_ratio REAL,
            green_ratio REAL,
            parking_ratio TEXT,
            total_units INTEGER,
            building_types TEXT,
            unit_sizes TEXT,
            avg_price REAL,
            listing_count INTEGER,
            features TEXT,
            coordinate_lng REAL,
            coordinate_lat REAL,
            data_source TEXT,
            data_updated TEXT,
            region_id TEXT DEFAULT 'yangling'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS community_poi (
            community_id TEXT NOT NULL,
            poi_type TEXT NOT NULL,
            poi_name TEXT NOT NULL,
            distance_m INTEGER,
            walk_time_min INTEGER,
            notes TEXT,
            region_id TEXT DEFAULT 'yangling',
            PRIMARY KEY (community_id, poi_type, poi_name)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS generated_scripts (
            script_id TEXT PRIMARY KEY,
            community_id TEXT,
            track_type TEXT NOT NULL,
            script_text TEXT,
            research_brief TEXT,
            generated_at TEXT DEFAULT (datetime('now')),
            region_id TEXT DEFAULT 'yangling'
        )
    """)

    # ── Migration: add detail-page enrichment columns ────────────

    detail_columns = {
        "on_sale_count": "INTEGER",
        "on_rent_count": "INTEGER",
        "price_trend_json": "TEXT",
        "surrounding_json": "TEXT",
        "community_review": "TEXT",
        "detail_scraped_at": "TEXT",
    }
    for col, col_type in detail_columns.items():
        if not _column_exists(conn, table="communities", column=col):
            conn.execute(f"ALTER TABLE communities ADD COLUMN {col} {col_type}")

    # ── Migration: add region_id to existing tables ────────────

    for table in ["communities", "community_poi", "generated_scripts"]:
        if not _column_exists(conn, table, "region_id"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN region_id TEXT DEFAULT 'yangling'")

    # ── Migration: 省市层级回填列 (province/city) ─────────────

    for table in ["communities", "districts"]:
        if not _column_exists(conn, table, "city_id"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN city_id TEXT")
        if not _column_exists(conn, table, "province_id"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN province_id TEXT")

    # ── Migration: 详情补充字段 (同页基本信息 / 小区解读 / 户型) ──

    _detail_json_cols = {
        "property_basic_json":            # 同页基本信息补充 (物业类型/权属/产权/面积/供暖/供水/停车费…)
            "ALTER TABLE communities ADD COLUMN property_basic_json TEXT",
        "community_interpretation_json":  # 小区解读 (轨道交通/户型/设施/生活配套/不足)
            "ALTER TABLE communities ADD COLUMN community_interpretation_json TEXT",
        "huxingtu_json":                  # 户型列表 (独立页 huxingtu, [{type,rooms,halls,area,image}])
            "ALTER TABLE communities ADD COLUMN huxingtu_json TEXT",
    }
    for col, sql in _detail_json_cols.items():
        if not _column_exists(conn, "communities", col):
            conn.execute(sql)

    # ── Douyin local content (replaces data/douyin_content.json) ─

    conn.execute("""
        CREATE TABLE IF NOT EXISTS douyin_local_content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region_id TEXT NOT NULL,
            community_name TEXT,
            desc TEXT NOT NULL,
            author TEXT,
            type TEXT,
            digg_count INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            keyword TEXT,
            fetched_at TEXT NOT NULL
        )
    """)

    # ── WeChat articles (replaces data/wechat_*.json) ──────────

    conn.execute("""
        CREATE TABLE IF NOT EXISTS wechat_articles (
            url TEXT PRIMARY KEY,
            region_id TEXT NOT NULL,
            title TEXT NOT NULL,
            account TEXT,
            publish_time TEXT,
            text TEXT NOT NULL,
            query TEXT,
            fetched_at TEXT NOT NULL
        )
    """)

    # ── Geographic hierarchy: provinces / cities ───────────────
    # 省 → 市(安居客子域) → 区 → 商圈 → 小区
    conn.execute("""
        CREATE TABLE IF NOT EXISTS provinces (
            province_id TEXT PRIMARY KEY,       -- GB/T 2260 省级码: '11' 北京
            name TEXT NOT NULL,                 -- 全称: 北京市 / 河北省
            short_name TEXT,                    -- 简称: 北京 / 河北
            type TEXT                           -- 直辖市 / 省 / 自治区 / 特别行政区
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cities (
            city_id TEXT PRIMARY KEY,           -- 安居客子域: 'beijing' / 'xianghe'
            name TEXT NOT NULL,                 -- 安居客名: 北京 / 香河
            province_id TEXT REFERENCES provinces(province_id),
            gb_name TEXT,                       -- 标准行政区划名: 北京市 / 香河县
            gb_city_code TEXT,                  -- 地级代码(县级市为父地级市)
            gb_area_code TEXT,                  -- 县级代码(地级市为 NULL)
            level TEXT,                         -- province / prefecture / county
            is_hot INTEGER DEFAULT 0,           -- 安居客热门城市
            created_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cities_province ON cities(province_id)")

    # ── Drop unused city_shangquan table ───────────────────────

    if _table_exists(conn, "city_shangquan"):
        conn.execute("DROP TABLE IF EXISTS city_shangquan")

    # ── Indexes ────────────────────────────────────────────────

    conn.execute("CREATE INDEX IF NOT EXISTS idx_communities_region ON communities(region_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_community_poi_region ON community_poi(region_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_community_poi_community ON community_poi(community_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_generated_scripts_community ON generated_scripts(community_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_generated_scripts_region ON generated_scripts(region_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_douyin_region ON douyin_local_content(region_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wechat_region ON wechat_articles(region_id)")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_tables()
    print("Schema created.")
