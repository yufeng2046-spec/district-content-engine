"""
Batch script generator — processes communities in bulk with rate limiting.

First principles:
- DeepSeek rate limit: ~60 RPM on paid tier. We target 10-15 RPM to be safe.
- Each Track A = 2 API calls (writer + editor), Track B = 2 API calls
- Cost: ~$0.001 per script. 15K scripts ≈ $15.
- Prioritize communities with coordinate data (most complete briefs).

Usage:
    PYTHONPATH=. python3 data/batch_generate.py --region yangling --track A
    PYTHONPATH=. python3 data/batch_generate.py --region chengdu_wuhou --track A --max 50
    PYTHONPATH=. python3 data/batch_generate.py --region yangling --track B
    PYTHONPATH=. python3 data/batch_generate.py --region yangling --track A --dry-run
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.connection import get_db
from db.schema import create_tables
from config import get_region, DEFAULT_REGION, REGIONS
from agents.researcher import assemble_community_brief, assemble_region_brief
from agents.writer import write_track_a, write_track_b
from agents.editor import edit

BASE_DIR = Path(__file__).resolve().parent.parent
PROGRESS_FILE = BASE_DIR / "data" / "batch_generate_progress.json"

# ── Rate limit (first principles: stay well under API limit) ──
API_DELAY_S = 6.0  # ~10 RPM — DeepSeek free tier is safe here
MAX_CONSECUTIVE_FAILURES = 5


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {}


def save_progress(data: dict) -> None:
    PROGRESS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def get_completed_scripts(region_id: str, track: str) -> set[str]:
    """Return set of community_ids that already have scripts."""
    conn = get_db()
    if track == "A":
        rows = conn.execute(
            "SELECT community_id FROM generated_scripts WHERE track_type=? AND region_id LIKE ?",
            (track, region_id.replace("*", "%")),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT region_id FROM generated_scripts WHERE track_type=? AND region_id LIKE ?",
            (track, region_id.replace("*", "%")),
        ).fetchall()
    conn.close()
    return {r[0] for r in rows if r[0]}


def get_pending_communities(region_id: str, max_count: int = 0) -> list[dict]:
    """Get communities that need Track A scripts, sorted by data completeness."""
    conn = get_db()
    # Prefer communities with coordinates + price (richest briefs)
    rows = conn.execute("""
        SELECT community_id, name, avg_price, coordinate_lng, coordinate_lat,
               address, year_built, developer, property_mgmt, property_fee,
               surrounding_json, community_review, detail_scraped_at
        FROM communities
        WHERE region_id LIKE ?
          AND name IS NOT NULL AND name != ''
        ORDER BY
            CASE WHEN coordinate_lng IS NOT NULL THEN 0 ELSE 1 END,
            CASE WHEN avg_price IS NOT NULL THEN 0 ELSE 1 END,
            CASE WHEN surrounding_json IS NOT NULL THEN 0 ELSE 1 END,
            CASE WHEN community_review IS NOT NULL THEN 0 ELSE 1 END,
            name
    """, (region_id,)).fetchall()
    conn.close()

    completed = get_completed_scripts(region_id, "A")
    pending = [dict(r) for r in rows if r["community_id"] not in completed]

    if max_count > 0:
        pending = pending[:max_count]
    return pending


def get_pending_regions(base_region_id: str) -> list[str]:
    """Get region IDs within a city/area that need Track B scripts."""
    completed = get_completed_scripts(base_region_id, "B")

    # Collect all relevant region IDs
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT region_id FROM communities WHERE region_id LIKE ?",
        (base_region_id,),
    ).fetchall()
    conn.close()

    return sorted([r[0] for r in rows if r[0] not in completed])


def generate_batch(
    region_id: str,
    track: str = "A",
    max_count: int = 0,
    dry_run: bool = False,
) -> dict:
    """Batch generate scripts with rate limiting and progress tracking."""
    create_tables()

    result = {
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "region_id": region_id,
        "track": track,
        "generated": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    if track == "A":
        communities = get_pending_communities(region_id, max_count)
        total = len(communities)
        print(f"\n{'='*60}")
        print(f"Batch Track A — {region_id}")
        print(f"  Pending: {total} communities")
        if dry_run:
            print(f"  [DRY RUN] Would generate {total} scripts")
            for c in communities[:5]:
                print(f"    {c['name']} (¥{c.get('avg_price','?')})")
            if total > 5:
                print(f"    ... and {total-5} more")
            return result
        print(f"  Rate: ~{60/API_DELAY_S:.0f} scripts/min")
        print(f"  Est. time: {total * API_DELAY_S / 60:.0f} min")
        print(f"{'='*60}")

        consecutive_failures = 0

        for idx, c in enumerate(communities):
            cid = c["community_id"]
            name = c["name"]
            print(f"\n[{idx+1}/{total}] {name} ({cid})")

            try:
                # Phase 0: Research
                brief = assemble_community_brief(cid, region_id=region_id)
                if brief.startswith("# 错误") or len(brief) < 50:
                    print(f"  ✗ Brief too short ({len(brief)} chars), skipping")
                    result["skipped"] += 1
                    continue

                if dry_run:
                    print(f"  [DRY RUN] Brief: {len(brief)} chars")
                    result["generated"] += 1
                    continue

                # Phase 1: Writer
                print(f"  Brief: {len(brief)} chars → generating...")
                draft = write_track_a(brief, region_name="")
                print(f"  Draft: {len(draft)} chars → editing...")

                # Rate limit between API calls
                time.sleep(2.0)

                # Phase 2: Editor
                final = edit(draft, brief)

                # Save to DB
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                script_id = f"{cid}_A_{ts}"

                # Get the actual region_id for this community
                conn = get_db()
                row = conn.execute(
                    "SELECT region_id FROM communities WHERE community_id = ?", (cid,)
                ).fetchone()
                script_region_id = row["region_id"] if row else region_id

                conn.execute(
                    """INSERT INTO generated_scripts
                       (script_id, community_id, track_type, script_text, research_brief, region_id)
                       VALUES (?, ?, 'A', ?, ?, ?)""",
                    (script_id, cid, final, brief, script_region_id),
                )
                conn.commit()
                conn.close()

                print(f"  ✓ {script_id} ({len(final)} chars)")
                result["generated"] += 1
                consecutive_failures = 0

                # Save progress
                save_progress({
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "last_community": cid,
                    "count": result["generated"],
                })

            except Exception as e:
                print(f"  ✗ Error: {e}")
                result["failed"] += 1
                result["errors"].append({"community": cid, "error": str(e)[:200]})
                consecutive_failures += 1

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"\n  ⚠️  {MAX_CONSECUTIVE_FAILURES} consecutive failures — stopping")
                    break

                time.sleep(5.0)  # Extra delay after errors
                continue

            # Rate limit between scripts
            if idx < total - 1:
                time.sleep(API_DELAY_S)

    elif track == "B":
        regions = get_pending_regions(region_id)
        total = len(regions)
        print(f"\n{'='*60}")
        print(f"Batch Track B — {region_id}")
        print(f"  Pending regions: {total}")
        if dry_run:
            print(f"  [DRY RUN] Would generate {total} region scripts")
            for r in regions[:5]:
                print(f"    {r}")
            return result
        print(f"{'='*60}")

        for idx, rid in enumerate(regions):
            print(f"\n[{idx+1}/{total}] Region: {rid}")
            try:
                brief = assemble_region_brief(region_id=rid)
                if brief.startswith("# 错误") or len(brief) < 30:
                    print(f"  ✗ Brief too short, skipping")
                    result["skipped"] += 1
                    continue

                r = get_region(rid) if rid in REGIONS else {"name": rid}
                region_name = r.get("name", rid)

                print(f"  Brief: {len(brief)} chars → generating...")
                draft = write_track_b(brief, region_name=region_name)

                time.sleep(2.0)

                print(f"  Draft: {len(draft)} chars → editing...")
                final = edit(draft, brief)

                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                script_id = f"{rid}_B_{ts}"

                conn = get_db()
                conn.execute(
                    """INSERT INTO generated_scripts
                       (script_id, community_id, track_type, script_text, research_brief, region_id)
                       VALUES (?, NULL, 'B', ?, ?, ?)""",
                    (script_id, final, brief, rid),
                )
                conn.commit()
                conn.close()

                print(f"  ✓ {script_id}")
                result["generated"] += 1

            except Exception as e:
                print(f"  ✗ Error: {e}")
                result["failed"] += 1
                result["errors"].append({"region": rid, "error": str(e)[:200]})

            if idx < total - 1:
                time.sleep(API_DELAY_S)

    # Summary
    elapsed = datetime.now() - datetime.strptime(result["started_at"], "%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"Batch complete: {result['generated']} generated, "
          f"{result['skipped']} skipped, {result['failed']} failed")
    print(f"Elapsed: {elapsed}")
    print(f"{'='*60}")

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch script generator")
    parser.add_argument("--region", default=DEFAULT_REGION, help="Region ID or pattern (e.g. chengdu_%)")
    parser.add_argument("--track", default="A", choices=["A", "B"], help="Track A (community) or B (region)")
    parser.add_argument("--max", type=int, default=0, help="Max communities/regions to process")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without generating")
    args = parser.parse_args()

    generate_batch(
        region_id=args.region,
        track=args.track,
        max_count=args.max,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
