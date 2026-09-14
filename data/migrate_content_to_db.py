#!/usr/bin/env python3
"""One-shot migration: move douyin_content.json + wechat_*.json into DB tables.

Usage:
    PYTHONPATH=. python3 data/migrate_content_to_db.py
    PYTHONPATH=. python3 data/migrate_content_to_db.py --dry-run
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.connection import get_db
from db.schema import create_tables
from config import REGIONS


def _infer_region_id(filepath: Path) -> str:
    """Infer region_id from filename: wechat_<region_id>.json → region_id."""
    stem = filepath.stem  # e.g. "wechat_content", "wechat_datong_pingcheng"
    if stem == "wechat_content":
        return "yangling"
    # wechat_datong_pingcheng → datong_pingcheng
    suffix = stem.replace("wechat_", "")
    if suffix in REGIONS:
        return suffix
    return suffix


def migrate_douyin(data_dir: Path, dry_run: bool = False) -> int:
    """Migrate douyin_content.json → douyin_local_content table."""
    src = data_dir / "douyin_content.json"
    if not src.exists():
        print(f"  Skip: {src} not found")
        return 0

    data = json.loads(src.read_text())
    results = data.get("results", [])
    summary = data.get("summary", {})

    # Infer region from summary or first result
    region_id = summary.get("region", "yangling")
    if isinstance(region_id, str):
        # Map "杨陵区" → "yangling"
        for rid, rcfg in REGIONS.items():
            if rcfg["name"] == region_id:
                region_id = rid
                break

    conn = get_db()
    count = 0
    for item in results:
        if dry_run:
            count += 1
            continue
        try:
            communities = item.get("communities_mentioned", [])
            community_name = ", ".join(communities) if isinstance(communities, list) else str(communities)
            conn.execute(
                """INSERT OR IGNORE INTO douyin_local_content
                   (region_id, community_name, desc, author, type, digg_count, comment_count, keyword, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    region_id,
                    community_name,
                    item.get("desc", ""),
                    item.get("author", ""),
                    item.get("type", ""),
                    int(item.get("digg_count", 0)),
                    int(item.get("comment_count", 0)),
                    str(item.get("keyword", summary.get("keywords", [""])[0] if summary.get("keywords") else "")),
                    item.get("fetched_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S") if not item.get("fetched_at") else item["fetched_at"]),
                ),
            )
            count += 1
        except Exception as e:
            print(f"  DB error: {e}")
    conn.commit()
    conn.close()

    print(f"  Douyin: {count} records {'(dry-run)' if dry_run else 'migrated'}")
    return count


def migrate_wechat(data_dir: Path, dry_run: bool = False) -> int:
    """Migrate wechat_content.json + wechat_*.json → wechat_articles table."""
    total = 0

    for src in data_dir.glob("wechat*.json"):
        region_id = _infer_region_id(src)
        data = json.loads(src.read_text())

        conn = get_db()
        count = 0
        for url, article in data.items():
            if dry_run:
                count += 1
                continue
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO wechat_articles
                       (url, region_id, title, account, publish_time, text, query, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        url,
                        region_id,
                        article.get("title", ""),
                        article.get("account", ""),
                        article.get("publish_time", ""),
                        article.get("text", ""),
                        article.get("query", ""),
                        article.get("fetched_at", ""),
                    ),
                )
                count += 1
            except Exception as e:
                print(f"  DB error for {url[:60]}: {e}")
        conn.commit()
        conn.close()

        print(f"  WeChat ({src.name} → {region_id}): {count} records {'(dry-run)' if dry_run else 'migrated'}")
        total += count

    return total


def main():
    create_tables()
    data_dir = BASE_DIR / "data"
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("[DRY RUN] Previewing migration...\n")

    d_count = migrate_douyin(data_dir, dry_run=dry_run)
    w_count = migrate_wechat(data_dir, dry_run=dry_run)

    print(f"\nTotal: {d_count} douyin + {w_count} wechat records {'(dry-run)' if dry_run else 'migrated'}")
    if dry_run:
        print("Run without --dry-run to execute the migration.")


if __name__ == "__main__":
    main()
