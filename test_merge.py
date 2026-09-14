#!/usr/bin/env python3
"""Adversarial tests for db/dbtransfer.py (export / import / merge_detail).

Uses throwaway SQLite DBs in a temp dir — never touches the live DB.

Run:
    python3 test_merge.py          # all tests, exit 0/1
"""
import os, sqlite3, tempfile, sys

sys.path.insert(0, os.path.dirname(__file__))
from db.dbtransfer import export_communities, import_communities

# Minimal subset of the real communities schema — enough to exercise the
# transfer logic (column-intersection keeps this robust to schema drift).
SCHEMA = """
CREATE TABLE communities (
    community_id   TEXT PRIMARY KEY,
    name           TEXT,
    region_id      TEXT,
    avg_price      REAL,
    detail_scraped_at TEXT,
    shangquan_id   TEXT,
    data_source    TEXT
)
"""

PASS = 0
FAIL = 0


def _mkdb(path, rows):
    c = sqlite3.connect(path)
    c.execute(SCHEMA)
    for r in rows:
        c.execute("INSERT INTO communities VALUES (?,?,?,?,?,?,?)", r)
    c.commit()
    c.close()


def _count(path):
    c = sqlite3.connect(path)
    n = c.execute("SELECT COUNT(*) FROM communities").fetchone()[0]
    c.close()
    return n


def _row(path, cid):
    c = sqlite3.connect(path)
    r = c.execute("SELECT community_id,name,region_id,avg_price,detail_scraped_at,shangquan_id,data_source "
                  "FROM communities WHERE community_id=?", (cid,)).fetchone()
    c.close()
    return r


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


def main():
    tmp = tempfile.mkdtemp(prefix="test_merge_")
    print("=== test_merge.py (dbtransfer adversarial) ===")

    # ── T1: export + import(ignore) count + re-import idempotency ──
    src = os.path.join(tmp, "src.db")
    dst = os.path.join(tmp, "dst.db")
    tf = os.path.join(tmp, "tf.db")
    _mkdb(src, [("a1", "A", "test_a", 100, None, None, "ajk"),
                ("a2", "B", "test_a", 200, None, None, "ajk"),
                ("b1", "C", "test_b", 300, None, None, "ajk")])
    _mkdb(dst, [])   # dst is a live DB with schema but no rows yet
    n = export_communities(src, tf, region_id="test_a")
    check("T1 export region filter → 2 rows (not 3)", n == 2)
    n2 = import_communities(dst, tf, mode="ignore")
    check("T1 import → 2 rows", _count(dst) == 2 and n2 == 2)
    n3 = import_communities(dst, tf, mode="ignore")
    check("T1 re-import idempotent → still 2 rows", _count(dst) == 2 and n3 == 0)

    # ── T2: ignore mode does NOT clobber existing row ──
    _mkdb(dst2 := os.path.join(tmp, "dst2.db"), [("a1", "A", "test_a", 100, None, None, "ajk")])
    # src has a1 with avg_price=999, detail set
    _mkdb(src2 := os.path.join(tmp, "src2.db"), [("a1", "A", "test_a", 999, "2026-08-24", "SQ", "ajk")])
    tf2 = os.path.join(tmp, "tf2.db")
    export_communities(src2, tf2)
    import_communities(dst2, tf2, mode="ignore")
    r = _row(dst2, "a1")
    check("T2 ignore keeps existing avg_price=100, detail NULL", r[3] == 100 and r[4] is None)

    # ── T3: merge_detail updates details, PRESERVES metadata ──
    _mkdb(dst3 := os.path.join(tmp, "dst3.db"),
          [("a1", "旧名", "test_a", 100, None, "SQ_local", "ajk")])
    _mkdb(src3 := os.path.join(tmp, "src3.db"),
          [("a1", "新名", "test_a", 250, "2026-08-24", "SQ_cube", "ajk")])
    tf3 = os.path.join(tmp, "tf3.db")
    export_communities(src3, tf3)
    n4 = import_communities(dst3, tf3, mode="merge_detail", predicate="detail_scraped_at IS NOT NULL")
    r = _row(dst3, "a1")
    check("T3 merge_detail updated avg_price=250 + detail set", r[3] == 250 and r[4] == "2026-08-24")
    check("T3 merge_detail PRESERVED name=旧名", r[1] == "旧名")
    check("T3 merge_detail PRESERVED shangquan_id=SQ_local", r[5] == "SQ_local")
    check("T3 affected=1", n4 == 1)

    # ── T4: fake community injection — imports cleanly, no crash ──
    tf4 = os.path.join(tmp, "tf4.db")
    _mkdb(tf4, [("fake_shenzhen_999", "假小区", "shenzhen", 12345, "2026-08-24", "SQ", "ajk")])
    n5 = import_communities(dst, tf4, mode="ignore")
    check("T4 fake row lands, count 2→3", _count(dst) == 3 and n5 == 1)

    # ── T5: merge_detail INSERT branch (new row, metadata from src) ──
    _mkdb(dst5 := os.path.join(tmp, "dst5.db"), [("x1", "X", "test_x", 1, None, None, "ajk")])
    tf5 = os.path.join(tmp, "tf5.db")
    export_communities(src3, tf5)  # a1 new row in dst5
    import_communities(dst5, tf5, mode="merge_detail")
    r = _row(dst5, "a1")
    check("T5 merge_detail inserts new row with all fields", r is not None and r[3] == 250 and r[4] == "2026-08-24")

    # ── T6: detail_only export filters correctly ──
    tf6 = os.path.join(tmp, "tf6.db")
    n6 = export_communities(src3, tf6, region_id="test_a", detail_only=True)
    check("T6 detail_only exports only rows with detail", n6 == 1)

    # ── T7: whole-table export (no region) ──
    tf7 = os.path.join(tmp, "tf7.db")
    n7 = export_communities(src, tf7)
    check("T7 no-region export → 3 rows", n7 == 3)

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
