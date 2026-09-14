"""
Migration: add districts + shangquans tables, and shangquan_id to communities.
Populates from shangquan_*.json files.
"""
import json, sys
from pathlib import Path
from db.connection import get_db

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def migrate():
    conn = get_db()
    cur = conn.cursor()

    # ═══ Create districts table ═══
    cur.execute("""
        CREATE TABLE IF NOT EXISTS districts (
            district_id   TEXT PRIMARY KEY,   -- beijing_chaoyang
            city          TEXT NOT NULL,       -- beijing
            city_name     TEXT NOT NULL,       -- 北京
            name          TEXT NOT NULL,       -- 朝阳
            slug          TEXT NOT NULL,       -- chaoyang
            url           TEXT,                -- https://beijing.anjuke.com/community/chaoyang/
            source_file   TEXT,                -- shangquan_beijing.json
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)

    # ═══ Create shangquans table ═══
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shangquans (
            shangquan_id  TEXT PRIMARY KEY,   -- beijing_chaoyang_cbd
            district_id   TEXT NOT NULL REFERENCES districts(district_id),
            city          TEXT NOT NULL,       -- beijing
            name          TEXT NOT NULL,       -- CBD
            slug          TEXT NOT NULL,       -- cbd (from URL)
            url           TEXT NOT NULL,        -- https://beijing.anjuke.com/community/chaoyang-q-cbd/
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)

    # ═══ Add shangquan_id to communities ═══
    try:
        cur.execute("ALTER TABLE communities ADD COLUMN shangquan_id TEXT REFERENCES shangquans(shangquan_id)")
        print("  ✅ Added shangquan_id column to communities")
    except Exception as e:
        if "duplicate" in str(e).lower():
            print("  ℹ️  shangquan_id column already exists")
        else:
            print(f"  ⚠️  {e}")

    # ═══ Indexes ═══
    cur.execute("CREATE INDEX IF NOT EXISTS idx_shangquans_district ON shangquans(district_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_communities_shangquan ON communities(shangquan_id)")

    # ═══ Populate from JSON files ═══
    json_files = sorted(DATA_DIR.glob("shangquan_*.json"))
    if not json_files:
        print("  ❌ No shangquan_*.json files found in data/")
        conn.close()
        return

    districts_inserted = 0
    shangquans_inserted = 0

    for jf in json_files:
        data = json.loads(jf.read_text())
        city_slug = data.get("city", jf.stem.replace("shangquan_", ""))
        city_name = data.get("city_name", city_slug)
        districts_data = data.get("districts", {})

        for dslug, ddata in districts_data.items():
            # Handle both old and new JSON formats
            if isinstance(ddata, dict):
                dname = ddata.get("name", ddata.get("slug", dslug))
                durl = ddata.get("url", f"https://{city_slug}.anjuke.com/community/{dslug}/")
                shangquans_list = ddata.get("shangquan", [])
            else:
                continue

            district_id = f"{city_slug}_{dslug}"

            # Insert district
            cur.execute("""
                INSERT OR REPLACE INTO districts (district_id, city, city_name, name, slug, url, source_file)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (district_id, city_slug, city_name, dname, dslug, durl, jf.name))
            districts_inserted += 1

            # Insert shangquans
            for sq in shangquans_list:
                sq_name = sq.get("name", "")
                sq_url = sq.get("url", "")
                if not sq_name or not sq_url:
                    continue

                # Extract slug from URL: /community/chaoyang-q-cbd/ → cbd
                sq_slug = ""
                parts = sq_url.rstrip("/").split("/")
                if len(parts) >= 2:
                    last = parts[-1]
                    # Handle -q- format: chaoyang-q-cbd → cbd
                    if "-q-" in last:
                        sq_slug = last.split("-q-", 1)[-1]
                    else:
                        sq_slug = last

                shangquan_id = f"{district_id}_{sq_slug}"

                cur.execute("""
                    INSERT OR REPLACE INTO shangquans (shangquan_id, district_id, city, name, slug, url)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (shangquan_id, district_id, city_slug, sq_name, sq_slug, sq_url))
                shangquans_inserted += 1

        print(f"  📄 {jf.name}: {city_name} — {len(districts_data)} districts")

    conn.commit()

    # ═══ Verify ═══
    district_count = cur.execute("SELECT COUNT(*) FROM districts").fetchone()[0]
    shangquan_count = cur.execute("SELECT COUNT(*) FROM shangquans").fetchone()[0]

    print()
    print("=" * 50)
    print(f"  districts:   {district_count} rows")
    print(f"  shangquans:  {shangquan_count} rows")
    print(f"  ✅ Migration complete")

    # Show summary by city
    print()
    for row in cur.execute("""
        SELECT d.city_name, COUNT(DISTINCT d.district_id), COUNT(s.shangquan_id)
        FROM districts d
        LEFT JOIN shangquans s ON s.district_id = d.district_id
        GROUP BY d.city, d.city_name
        ORDER BY COUNT(s.shangquan_id) DESC
    """).fetchall():
        print(f"  {row[0]:6s}: {row[1]:>2}区, {row[2]:>3}商圈")

    conn.close()


if __name__ == "__main__":
    migrate()
