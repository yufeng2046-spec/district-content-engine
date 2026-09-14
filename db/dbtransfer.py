"""Transfer community rows between two SQLite DBs via compact transfer files.

Purpose: dual-machine parallel crawling. Each machine writes its own
district_content.db. This module moves only the *assigned region's* rows:

  - export_communities():  read a region's rows from a source DB into a fresh
                           compact .db file (SELECT-built snapshot → WAL-safe,
                           never a raw copy of the live file).
  - import_communities():  read a transfer file into a target DB.
        mode='ignore'      INSERT OR IGNORE — idempotent pre-seed, never clobbers.
        mode='replace'     INSERT OR REPLACE — full-row overwrite (use with care).
        mode='merge_detail' UPSERT updating ONLY detail columns, preserving local
                           metadata (region_id/shangquan_id/city_id/province_id/
                           district_id/name/address/data_source). Idempotent.
"""
from __future__ import annotations

import os
import sqlite3


def _connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path if not readonly else f"file:{path}?mode=ro",
        uri=readonly,
        timeout=60,
    )
    conn.execute("PRAGMA busy_timeout=60000")
    conn.row_factory = sqlite3.Row
    return conn


def _cols(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _mirror_schema(dst: sqlite3.Connection, src: sqlite3.Connection, table: str) -> None:
    """Recreate src table's schema (types + PK) on dst."""
    info = src.execute(f"PRAGMA table_info({table})").fetchall()
    cols = [f'"{r[1]}" {r[2]}' + (" NOT NULL" if r[3] else "") for r in info]
    pks = [r[1] for r in info if r[5] > 0]
    if pks:
        cols.append("PRIMARY KEY (" + ",".join(f'"{p}"' for p in pks) + ")")
    dst.execute(f'CREATE TABLE "{table}" (' + ",".join(cols) + ")")


# Columns that are local-machine-owned metadata. merge_detail never overwrites these.
PRESERVED_COLS = {
    "community_id",  # PK, conflict target
    "name",
    "address",
    "data_source",
    "region_id",
    "shangquan_id",
    "city_id",
    "province_id",
    "district_id",
}


def export_communities(src_db: str, out_path: str,
                       region_id: str | None = None,
                       region_like: str | None = None,
                       detail_only: bool = False) -> int:
    """Copy a region's community rows from src_db into a fresh transfer file.

    region_id     exact region_id match (e.g. 'shenzhen').
    region_like   SQL LIKE pattern over region_id (e.g. 'chengdu_%').
    detail_only=True → only rows with detail_scraped_at IS NOT NULL (for pulling
    finished crawl results back).
    Returns number of rows exported.
    """
    src = _connect(src_db, readonly=True)
    cols = _cols(src, "communities")
    if os.path.exists(out_path):
        os.remove(out_path)
    dst = _connect(out_path)
    _mirror_schema(dst, src, "communities")
    colsql = ",".join(f'"{c}"' for c in cols)
    where, params = [], []
    if region_id:
        where.append("region_id = ?")
        params.append(region_id)
    if region_like:
        where.append("region_id LIKE ?")
        params.append(region_like)
    if detail_only:
        where.append("detail_scraped_at IS NOT NULL")
    sql = f"SELECT {colsql} FROM communities" + ((" WHERE " + " AND ".join(where)) if where else "")
    rows = src.execute(sql, params).fetchall()
    placeholders = ",".join("?" * len(cols))
    dst.executemany(f"INSERT INTO communities VALUES ({placeholders})",
                    [tuple(r[c] for c in cols) for r in rows])
    dst.commit()
    n = len(rows)
    dst.close()
    src.close()
    return n


def import_communities(dst_db: str, in_path: str,
                       mode: str = "ignore",
                       predicate: str | None = None) -> int:
    """Import a transfer file into dst_db. Returns rows affected.

    mode:
      ignore       → INSERT OR IGNORE (pre-seed, idempotent, never clobbers)
      replace      → INSERT OR REPLACE (full-row overwrite)
      merge_detail → UPSERT, updates only PRESERVED-excluded columns
    predicate is an optional SQL fragment applied to the src SELECT, e.g.
    "detail_scraped_at IS NOT NULL".
    """
    if mode not in ("ignore", "replace", "merge_detail"):
        raise ValueError(f"unknown mode: {mode!r}")
    dst = _connect(dst_db)
    src = _connect(in_path, readonly=True)
    dst_cols = _cols(dst, "communities")
    src_cols = _cols(src, "communities")
    # Use the column intersection: if src has extra columns dst lacks (e.g. a
    # newer local schema), drop them; if dst has NOT NULL columns src lacks,
    # the INSERT will fail loudly with a clear SQLite error — correct behavior.
    dropped = [c for c in src_cols if c not in dst_cols]
    dst_cols = [c for c in dst_cols if c in src_cols]
    if dropped:
        print(f"  [dbtransfer] dropping src-only columns not in dst: {dropped}")
    if not dst_cols:
        dst.close(); src.close()
        raise ValueError("no common columns between src and dst")
    dst_colsql = ",".join(f'"{c}"' for c in dst_cols)
    src_colsql = ",".join(f's."{c}"' for c in dst_cols)
    where = f" WHERE {predicate}" if predicate else ""

    dst.execute("ATTACH DATABASE ? AS src", (in_path,))
    try:
        if mode == "merge_detail":
            detail_cols = [c for c in dst_cols if c not in PRESERVED_COLS]
            upd = ", ".join(f'"{c}"=excluded."{c}"' for c in detail_cols)
            sql = (f"INSERT INTO main.communities ({dst_colsql}) "
                   f"SELECT {src_colsql} FROM src.communities s{where} "
                   f"ON CONFLICT(community_id) DO UPDATE SET {upd}")
            try:
                dst.execute("BEGIN")
                cur = dst.execute(sql)
                dst.execute("COMMIT")
            except sqlite3.OperationalError as e:
                # SQLite < 3.24: no UPSERT support. Fall back to row-by-row.
                if "syntax" not in str(e).lower():
                    raise
                dst.execute("ROLLBACK")
                n = _import_merge_fallback(dst, in_path, dst_cols, detail_cols, predicate)
                return n
        else:
            verb = "OR IGNORE" if mode == "ignore" else "OR REPLACE"
            sql = (f"INSERT {verb} INTO main.communities ({dst_colsql}) "
                   f"SELECT {src_colsql} FROM src.communities s{where}")
            dst.execute("BEGIN")
            cur = dst.execute(sql)
            dst.execute("COMMIT")
        return cur.rowcount
    finally:
        try:
            dst.execute("DETACH DATABASE src")
        except sqlite3.Error:
            pass
        dst.close()
        src.close()


def _import_merge_fallback(dst: sqlite3.Connection, in_path: str,
                           dst_cols: list[str], detail_cols: list[str],
                           predicate: str | None) -> int:
    """UPDATE-then-INSERT fallback for SQLite < 3.24 (no UPSERT)."""
    src = _connect(in_path, readonly=True)
    cols = [c for c in dst_cols if c in src_columns(src)]
    colsql = ",".join(f'"{c}"' for c in cols)
    src_rows = src.execute(f"SELECT {colsql} FROM communities" +
                           (f" WHERE {predicate}" if predicate else "")).fetchall()
    upd = ", ".join(f'"{c}"=excluded."{c}"' for c in detail_cols)
    n = 0
    dst.execute("BEGIN")
    for row in src_rows:
        d = dict(row)
        cid = d["community_id"]
        cur = dst.execute("SELECT 1 FROM communities WHERE community_id = ?", (cid,))
        if cur.fetchone():
            set_sql = ", ".join(f'"{c}"=?' for c in detail_cols)
            dst.execute(f"UPDATE communities SET {set_sql} WHERE community_id = ?",
                        [d[c] for c in detail_cols] + [cid])
        else:
            ins_cols = [c for c in cols if c in d]
            placeholders = ",".join("?" * len(ins_cols))
            ins_sql_cols = ",".join(f'"{c}"' for c in ins_cols)
            dst.execute(f"INSERT INTO communities ({ins_sql_cols}) "
                        f"VALUES ({placeholders})", [d[c] for c in ins_cols])
        n += 1
    dst.execute("COMMIT")
    src.close()
    return n


def src_columns(src: sqlite3.Connection) -> list[str]:
    return [r[1] for r in src.execute("PRAGMA table_info(communities)")]


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    op = sys.argv[1]
    def _arg(name, default=None):
        for i, a in enumerate(sys.argv[2:]):
            if a == name and i + 1 < len(sys.argv[2:]):
                return sys.argv[2:][i + 1]
        return default
    if op == "export":
        n = export_communities(
            _arg("--src"), _arg("--out"),
            region_id=_arg("--region"),
            detail_only=bool(_arg("--detail-only", "")),
        )
        print(f"exported {n} rows → {_arg('--out')}")
    elif op == "import":
        n = import_communities(
            _arg("--dst"), _arg("--in"),
            mode=_arg("--mode", "ignore"),
            predicate=_arg("--predicate"),
        )
        print(f"imported {n} rows → {_arg('--dst')} (mode={_arg('--mode', 'ignore')})")
    else:
        print(f"unknown op: {op}")
        sys.exit(1)
