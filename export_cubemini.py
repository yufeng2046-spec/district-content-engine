# DEPRECATED (2026-07-23): One-off data migration script, no longer needed.
# Data sync now happens via sync_state_to_cubemini.py. Kept for reference.
"""Export CubeMini communities for sync to local."""
import json, sys
sys.path.insert(0, '/home/frank/district-content-engine')
from db.connection import get_db

conn = get_db()
for region in ['shanghai', 'guangzhou', 'shenzhen']:
    rows = conn.execute(
        "SELECT * FROM communities WHERE region_id = ?", (region,)
    ).fetchall()
    if rows:
        cols = list(rows[0].keys())
        data = [dict(zip(cols, row)) for row in rows]
    fname = f'/tmp/export_{region}.json'
    with open(fname, 'w') as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    print(f'Exported {len(data):,} rows to {fname}')
conn.close()
