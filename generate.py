#!/usr/bin/env python3
"""Generate property video scripts for Yangling district.

Usage:
    PYTHONPATH=. python3 generate.py --track A --community yangling_xxx
    PYTHONPATH=. python3 generate.py --track B
    PYTHONPATH=. python3 generate.py --track A --list       # list available communities
"""

import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db.connection import get_db
from db.schema import create_tables
from agents.researcher import assemble_community_brief, assemble_region_brief
from agents.writer import write_track_a, write_track_b
from agents.editor import edit

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def list_communities():
    conn = get_db()
    rows = conn.execute(
        "SELECT community_id, name, avg_price FROM communities ORDER BY name"
    ).fetchall()
    conn.close()
    if not rows:
        print("No communities in DB. Run scraper first.")
        return
    for r in rows:
        print(f"  {r['community_id']:40s} {r['name']:20s} {r['avg_price'] or '?'}元/平")


def generate_track_a(community_id: str, skip_edit: bool = False):
    print(f"\n{'='*60}")
    print(f"Track A — 小区探盘: {community_id}")
    print(f"{'='*60}")

    # Phase 0: Research
    print("\n[Phase 0] Research — assembling brief...")
    brief = assemble_community_brief(community_id)
    print(f"  Brief: {len(brief)} chars")

    if brief.startswith("# 错误") or len(brief) < 50:
        print(f"\n  ERROR: Could not assemble research brief. Check community ID.")
        print(f"  Brief: {brief[:200]}")
        return

    # Phase 1: Writer
    print("\n[Phase 1] Writer — generating script...")
    draft = write_track_a(brief)
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
    conn.execute(
        """INSERT INTO generated_scripts (script_id, community_id, track_type, script_text, research_brief)
           VALUES (?, ?, 'A', ?, ?)""",
        (script_id, community_id, final, brief),
    )
    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Final script:\n{final}")
    print(f"{'='*60}")


def generate_track_b(skip_edit: bool = False):
    print(f"\n{'='*60}")
    print(f"Track B — 区域口播: 杨陵区")
    print(f"{'='*60}")

    # Phase 0: Research
    print("\n[Phase 0] Research — assembling region brief...")
    brief = assemble_region_brief()
    print(f"  Brief: {len(brief)} chars")

    # Phase 1: Writer
    print("\n[Phase 1] Writer — generating script...")
    draft = write_track_b(brief)
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
    script_id = f"yangling_region_B_{ts}"
    out_path = OUTPUT_DIR / f"{script_id}.md"

    out_path.write_text(
        f"# Track B 区域口播脚本\n\n"
        f"**区域**: 杨陵区\n"
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
        """INSERT INTO generated_scripts (script_id, community_id, track_type, script_text, research_brief)
           VALUES (?, NULL, 'B', ?, ?)""",
        (script_id, final, brief),
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

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--track" and i + 1 < len(args):
            track = args[i + 1].upper()
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
        list_communities()
        return

    if track == "A":
        if not community_id:
            print("Track A requires --community <id>. Use --list to see options.")
            sys.exit(1)
        generate_track_a(community_id, skip_edit=skip_edit)
    elif track == "B":
        generate_track_b(skip_edit=skip_edit)
    else:
        print(f"Unknown track: {track}. Use A or B.")
        sys.exit(1)


if __name__ == "__main__":
    main()
