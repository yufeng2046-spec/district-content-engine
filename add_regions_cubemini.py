"""Add Shanghai/Guangzhou/Shenzhen district configs to CubeMini config.py."""
import json, re
from pathlib import Path

BASE = Path('/home/frank/district-content-engine')
DATA = BASE / 'data'

with open(BASE / 'config.py', 'r') as f:
    content = f.read()

# Find insertion point (before the closing brace or at end of REGIONS)
lines = content.split('\n')
new_entries = []

for city_slug, city_name in [('shanghai', '上海'), ('guangzhou', '广州'), ('shenzhen', '深圳')]:
    sq_file = DATA / f'shangquan_{city_slug}.json'
    if not sq_file.exists():
        print(f'  ⚠️  {sq_file} not found, skipping')
        continue
    d = json.loads(sq_file.read_text())
    for dist_slug, dist_info in d['districts'].items():
        dist_name = dist_info.get('name') or dist_slug
        name_cn = dist_slug  # JSON keys are Chinese names for SH/GZ/SZ
        entry = f'''    "{city_slug}_{dist_slug}": {{
        "id": "{city_slug}_{dist_slug}",
        "name": "{name_cn}",
        "city": "{city_name}",
        "province": "{city_name}",
        "anjuke_url": "https://{city_slug}.anjuke.com/community/{dist_slug}/",
        "douyin_keywords": [],
        "wechat_keywords": [],
        "wechat_region_terms": [],
        "wechat_exclude_terms": [],
        "gaode_city": "{city_name}",
    }}'''
        new_entries.append(entry)
        print(f'  + {city_slug}_{dist_slug}: {name_cn}')

# Insert before DEFAULT_REGION or at appropriate place
insert_marker = 'DEFAULT_REGION'
inserted = []
for line in lines:
    inserted.append(line)
    if insert_marker in line and '=' in line:
        for entry in new_entries:
            inserted.insert(-1, entry)
        new_entries = []  # Only insert once

if new_entries:
    # Fallback: append at end
    inserted.extend(new_entries)

with open(BASE / 'config.py', 'w') as f:
    f.write('\n'.join(inserted))

print(f'\nAdded {len([e for e in inserted if "anjuke_url" in e])} region entries')
