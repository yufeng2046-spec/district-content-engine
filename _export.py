import sys, json
sys.path.insert(0, '/home/frank/district-content-engine')
from db.connection import get_db
conn = get_db()
rows = conn.execute("SELECT * FROM communities WHERE region_id=?", ('shanghai_pudong',)).fetchall()
cols = list(rows[0].keys()) if rows else []
data = [dict(zip(cols, r)) for r in rows]
with open('/tmp/pudong_export.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, default=str)
print(f'Exported {len(data)} rows')
conn.close()
