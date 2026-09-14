# DEPRECATED (2026-07-23): Use data/scrape_anjuke.py --region {city}_{district} --shangquan all directly.
# The main scraper natively supports batch district scraping. Kept for reference.
"""Batch district scraper for CubeMini — iterate all districts of a city."""
import asyncio, json, sys, time
from pathlib import Path

BASE = Path('/home/frank/district-content-engine')
DATA = BASE / 'data'
PYTHON = '/home/frank/crawler-venv/bin/python3'
SCRAPE_SCRIPT = BASE / 'data' / 'scrape_anjuke.py'

async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 cube_batch.py <city_slug> [--limit N]")
        print("  city_slug: shanghai, guangzhou, shenzhen")
        return

    city_slug = sys.argv[1]
    limit = 0
    for i, a in enumerate(sys.argv):
        if a == '--limit' and i + 1 < len(sys.argv):
            limit = int(sys.argv[i+1])

    sq_file = DATA / f'shangquan_{city_slug}.json'
    if not sq_file.exists():
        print(f"No shangquan file: {sq_file}")
        return

    d = json.loads(sq_file.read_text())
    districts = list(d['districts'].items())

    if limit > 0:
        districts = districts[:limit]

    city_name = d.get('city_name', city_slug)
    print(f"City: {city_name} ({city_slug}) — {len(districts)} districts")

    total_ok = 0
    total_fail = 0

    for idx, (dist_slug, dist_info) in enumerate(districts):
        region_id = f'{city_slug}_{dist_slug}'
        sq_count = len(dist_info.get('shangquan', []))
        print(f"\n{'='*60}")
        print(f"[{idx+1}/{len(districts)}] {region_id} — {sq_count} shangquans")
        print(f"{'='*60}")

        import subprocess
        result = subprocess.run(
            [PYTHON, str(SCRAPE_SCRIPT), '--region', region_id, '--shangquan', 'all'],
            cwd=str(BASE),
            env={**__import__('os').environ, 'PYTHONPATH': str(BASE)},
        )

        if result.returncode == 0:
            total_ok += 1
            print(f"  ✅ {region_id} completed")
        else:
            total_fail += 1
            print(f"  ❌ {region_id} failed (exit {result.returncode})")

        # Brief pause between districts
        if idx < len(districts) - 1:
            print(f"  Waiting 10s before next district...")
            time.sleep(10)

    print(f"\n{'='*60}")
    print(f"Batch complete: {total_ok} OK, {total_fail} failed, {len(districts)} total")
    print(f"{'='*60}")

if __name__ == '__main__':
    asyncio.run(main())
