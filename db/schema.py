"""Database schema — 3 core tables for MVP."""

from db.connection import get_db


def create_tables() -> None:
    conn = get_db()

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
            data_updated TEXT
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
            generated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_tables()
    print("Schema created.")
