import sys; sys.path.insert(0, '/home/frank/district-content-engine')
from db.connection import get_db
conn = get_db()
c = conn.execute
tot = c("SELECT COUNT(*) FROM communities WHERE region_id='shanghai_pudong'").fetchone()[0]
det = c("SELECT COUNT(*) FROM communities WHERE region_id='shanghai_pudong' AND detail_scraped_at IS NOT NULL").fetchone()[0]
sq  = c("SELECT COUNT(*) FROM communities WHERE region_id='shanghai_pudong' AND shangquan_id IS NOT NULL").fetchone()[0]
d   = c("SELECT COUNT(DISTINCT shangquan_id) FROM communities WHERE region_id='shanghai_pudong'").fetchone()[0]
print(f"浦东: {tot}小区 {det}详情 {sq}商圈ID {d}个商圈")
conn.close()
