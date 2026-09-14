"""Generate auto_regions.json from shangquan JSONs. Minimal config for scraping."""
import json
from pathlib import Path

BASE = Path('/home/frank/district-content-engine')
DATA = BASE / 'data'

auto_regions = {}
city_names = {
    'shanghai': '上海', 'guangzhou': '广州', 'shenzhen': '深圳',
    'beijing': '北京', 'chengdu': '成都', 'xa': '西安',
    'datong': '大同', 'langfang': '廊坊', 'yangling': '杨凌',
}

for sq_file in sorted(DATA.glob('shangquan_*.json')):
    d = json.loads(sq_file.read_text())
    city_slug = d.get('city', sq_file.stem.replace('shangquan_', ''))
    city_name = d.get('city_name') or city_names.get(city_slug, city_slug)

    for dist_slug in d['districts']:
        region_id = f'{city_slug}_{dist_slug}'
        auto_regions[region_id] = {
            'id': region_id,
            'name': dist_slug,  # slug used for filtering
            'city': city_name,
            'province': city_name,
            'anjuke_url': f'https://{city_slug}.anjuke.com/community/{dist_slug}/',
            'gaode_city': city_name,
        }

out_file = DATA / 'auto_regions.json'
out_file.write_text(json.dumps(auto_regions, ensure_ascii=False, indent=2))
print(f'Generated {len(auto_regions)} region configs → {out_file}')
