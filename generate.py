#!/usr/bin/env python3
"""Generate property video scripts for any registered region.

Usage:
    PYTHONPATH=. python3 generate.py --track A --region <id> --community <id>
    PYTHONPATH=. python3 generate.py --track B --region <id>
    PYTHONPATH=. python3 generate.py --track A --list --region <id>
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db.connection import get_db
from db.schema import create_tables
from config import get_region, DEFAULT_REGION
from agents.researcher import assemble_community_brief, assemble_region_brief
from agents.writer import write_track_a, write_track_b
from agents.editor import edit

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def list_communities(region_id: str | None = None):
    conn = get_db()
    if region_id:
        rows = conn.execute(
            "SELECT community_id, name, avg_price FROM communities WHERE region_id = ? ORDER BY name",
            (region_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT community_id, name, avg_price FROM communities ORDER BY name"
        ).fetchall()
    conn.close()
    if not rows:
        print(f"No communities in DB{' for ' + region_id if region_id else ''}. Run scraper first.")
        return
    for r in rows:
        print(f"  {r['community_id']:40s} {r['name']:20s} {r['avg_price'] or '?'}元/平")


def generate_track_a(community_id: str, region_id: str | None = None, skip_edit: bool = False):
    r = get_region(region_id)
    region_name = r["name"]
    print(f"\n{'='*60}")
    print(f"Track A — 小区探盘: {community_id}")
    print(f"{'='*60}")

    # Phase 0: Research
    print("\n[Phase 0] Research — assembling brief...")
    brief = assemble_community_brief(community_id, region_id=region_id)
    print(f"  Brief: {len(brief)} chars")

    if brief.startswith("# 错误") or len(brief) < 50:
        print(f"\n  ERROR: Could not assemble research brief. Check community ID.")
        print(f"  Brief: {brief[:200]}")
        return

    # Phase 1: Writer
    print("\n[Phase 1] Writer — generating script...")
    draft = write_track_a(brief, region_name=region_name)
    print(f"  Draft: {len(draft)} chars")

    if skip_edit:
        final = draft
        print("\n[Phase 2] Editor — SKIPPED")
    else:
        # Phase 2: Editor
        print("\n[Phase 2] Editor — reviewing...")
        final = edit(draft, brief)
        print(f"  Final: {len(final)} chars")

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_id = f"{community_id}_A_{ts}"
    out_path = OUTPUT_DIR / f"{script_id}.md"

    out_path.write_text(
        f"# Track A 小区探盘脚本\n\n"
        f"**小区ID**: {community_id}\n"
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"---\n\n"
        f"## 研究简报\n\n{brief}\n\n"
        f"---\n\n"
        f"## 脚本\n\n{final}\n",
        encoding="utf-8",
    )
    print(f"\n  Saved: {out_path}")

    # Save to DB
    conn = get_db()
    # Derive region_id from the community's record or fall back to parameter
    row = conn.execute(
        "SELECT region_id FROM communities WHERE community_id = ?", (community_id,)
    ).fetchone()
    script_region_id = row["region_id"] if row else (region_id or "yangling")

    conn.execute(
        """INSERT INTO generated_scripts (script_id, community_id, track_type, script_text, research_brief, region_id)
           VALUES (?, ?, 'A', ?, ?, ?)""",
        (script_id, community_id, final, brief, script_region_id),
    )
    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Final script:\n{final}")
    print(f"{'='*60}")


def generate_track_b(region_id: str | None = None, skip_edit: bool = False):
    r = get_region(region_id)
    region_name = r["name"]
    print(f"\n{'='*60}")
    print(f"Track B — 区域口播: {region_name}")
    print(f"{'='*60}")

    # Phase 0: Research
    print("\n[Phase 0] Research — assembling region brief...")
    brief = assemble_region_brief(region_id=region_id)
    print(f"  Brief: {len(brief)} chars")

    # Phase 1: Writer
    print("\n[Phase 1] Writer — generating script...")
    draft = write_track_b(brief, region_name=region_name)
    print(f"  Draft: {len(draft)} chars")

    if skip_edit:
        final = draft
        print("\n[Phase 2] Editor — SKIPPED")
    else:
        # Phase 2: Editor
        print("\n[Phase 2] Editor — reviewing...")
        final = edit(draft, brief)
        print(f"  Final: {len(final)} chars")

    # Save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_id = f"{region_id}_region_B_{ts}"
    out_path = OUTPUT_DIR / f"{script_id}.md"

    out_path.write_text(
        f"# Track B 区域口播脚本\n\n"
        f"**区域**: {region_name}\n"
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"---\n\n"
        f"## 研究简报\n\n{brief}\n\n"
        f"---\n\n"
        f"## 脚本\n\n{final}\n",
        encoding="utf-8",
    )
    print(f"\n  Saved: {out_path}")

    # Save to DB
    conn = get_db()
    conn.execute(
        """INSERT INTO generated_scripts (script_id, community_id, track_type, script_text, research_brief, region_id)
           VALUES (?, NULL, 'B', ?, ?, ?)""",
        (script_id, final, brief, region_id if region_id else "yangling"),
    )
    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Final script:\n{final}")
    print(f"{'='*60}")


def main():
    create_tables()

    track = "A"
    community_id = None
    list_mode = False
    skip_edit = False

    region_id = DEFAULT_REGION
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--track" and i + 1 < len(args):
            track = args[i + 1].upper()
            i += 2
        elif args[i] == "--region" and i + 1 < len(args):
            region_id = args[i + 1]
            i += 2
        elif args[i] == "--community" and i + 1 < len(args):
            community_id = args[i + 1]
            i += 2
        elif args[i] == "--list":
            list_mode = True
            i += 1
        elif args[i] == "--no-edit":
            skip_edit = True
            i += 1
        else:
            i += 1

    if list_mode:
        list_communities(region_id)
        return

    if track == "A":
        if not community_id:
            print("Track A requires --community <id>. Use --list to see options.")
            sys.exit(1)
        generate_track_a(community_id, region_id=region_id, skip_edit=skip_edit)
    elif track == "B":
        generate_track_b(region_id=region_id, skip_edit=skip_edit)
    else:
        print(f"Unknown track: {track}. Use A or B.")
        sys.exit(1)


if __name__ == "__main__":
    main()
