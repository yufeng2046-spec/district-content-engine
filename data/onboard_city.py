"""
City onboarding orchestrator — "开城" pipeline (automated edition).

Takes a Chinese city name and runs all phases automatically:
  0. City discovery    → find Anjuke subdomain & generate shangquan_{city}.json
  1. Activity assess   → sort districts by listing volume, split core vs outskirts
  2. Listings          → scrape listing pages for core districts (by 商圈)
  3. Details           → enrich detail pages for core districts
  4. Douyin            → fetch local Douyin content → douyin_local_content table
  5. WeChat            → fetch local WeChat articles → wechat_articles table

Usage:
    python3 data/onboard_city.py --city 西安
    python3 data/onboard_city.py --city 西安 --anjuke-url https://xian.anjuke.com/
    python3 data/onboard_city.py --city 西安 --include-all        # core + outskirts
    python3 data/onboard_city.py --city 西安 --outskirts-only     # outskirts only
    python3 data/onboard_city.py --city 西安 --from-phase 3       # resume from phase
    python3 data/onboard_city.py --city 西安 --dry-run            # print plan only
    python3 data/onboard_city.py --region beijing_haidian --from-phase 3  # existing region
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import REGIONS, get_region, DEFAULT_REGION, USER_AGENT
from db.connection import get_db
from db.schema import create_tables

STATE_FILE = BASE_DIR / ".pipeline_state.json"

# ── City name → Anjuke subdomain lookup ──────────────────────

# Common Anjuke city subdomains
_ANJUKE_CITY_MAP: dict[str, str] = {
    "北京": "beijing",
    "上海": "shanghai",
    "广州": "guangzhou",
    "深圳": "shenzhen",
    "成都": "chengdu",
    "杭州": "hangzhou",
    "武汉": "wuhan",
    "南京": "nanjing",
    "天津": "tianjin",
    "重庆": "chongqing",
    "西安": "xa",
    "长沙": "changsha",
    "郑州": "zhengzhou",
    "合肥": "hefei",
    "苏州": "suzhou",
    "济南": "jinan",
    "青岛": "qingdao",
    "大连": "dalian",
    "沈阳": "shenyang",
    "长春": "changchun",
    "哈尔滨": "haerbin",
    "福州": "fuzhou",
    "厦门": "xiamen",
    "南昌": "nanchang",
    "昆明": "kunming",
    "贵阳": "guiyang",
    "南宁": "nanning",
    "海口": "haikou",
    "三亚": "sanya",
    "太原": "taiyuan",
    "石家庄": "shijiazhuang",
    "兰州": "lanzhou",
    "西宁": "xining",
    "银川": "yinchuan",
    "呼和浩特": "huhehaote",
    "拉萨": "lasa",
    "乌鲁木齐": "wulumuqi",
    "东莞": "dongguan",
    "佛山": "foshan",
    "无锡": "wuxi",
    "常州": "changzhou",
    "珠海": "zhuhai",
    "惠州": "huizhou",
    "中山": "zhongshan",
    "嘉兴": "jiaxing",
    "绍兴": "shaoxing",
    "温州": "wenzhou",
    "金华": "jinhua",
    "台州": "taizhou",
    "南通": "nantong",
    "徐州": "xuzhou",
    "扬州": "yangzhou",
    "洛阳": "luoyang",
    "襄阳": "xiangyang",
    "宜昌": "yichang",
    "赣州": "ganzhou",
    "九江": "jiujiang",
    "桂林": "guilin",
    "柳州": "liuzhou",
    "咸阳": "xianyang",
    "宝鸡": "baoji",
    "渭南": "weinan",
    "延安": "yanan",
    "榆林": "yulin-shaanxi",
    "大同": "datong",
    "运城": "yuncheng",
    "临汾": "linfen",
    "保定": "baoding",
    "唐山": "tangshan",
    "廊坊": "langfang",
    "邯郸": "handan",
    "秦皇岛": "qinhuangdao",
    "承德": "chengde",
    "张家口": "zhangjiakou",
    "威海": "weihai",
    "烟台": "yantai",
    "潍坊": "weifang",
    "淄博": "zibo",
    "济宁": "jining",
    "临沂": "linyi",
    "泰安": "taian",
    "芜湖": "wuhu",  # wuhu for 芜湖
    "安庆": "anqing",
    "蚌埠": "bengbu",
    "阜阳": "fuyang",
    "马鞍山": "maanshan",
    "泉州": "quanzhou",
    "漳州": "zhangzhou",
    "莆田": "putian",
    "龙岩": "longyan",
    "宜昌": "yichang-sichuan",
    "荆州": "jingzhou",
    "黄石": "huangshi",
    "十堰": "shiyan",
    "岳阳": "yueyang",
    "株洲": "zhuzhou",
    "湘潭": "xiangtan",
    "衡阳": "hengyang",
    "常德": "changde",
    "郴州": "chenzhou",
    "绵阳": "mianyang",
    "德阳": "deyang",
    "宜宾": "yibin",
    "南充": "nanchong",
    "泸州": "luzhou",
    "乐山": "leshan",
    "达州": "dazhou",
    "自贡": "zigong",
    "攀枝花": "panzhihua",
    "遵义": "zunyi",
}

# Cities we already have coverage for (skip or only run details)
_COVERED_CITIES = {"北京", "成都", "大同", "咸阳"}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── State management ──────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def init_state(city: str, city_slug: str) -> dict:
    state = load_state()
    key = f"{city}_{city_slug}"
    if key not in state:
        state[key] = {
            "city": city,
            "city_slug": city_slug,
            "started_at": now_str(),
            "phases": {},
        }
    return state


def mark_phase(state: dict, key: str, phase_name: str, status: str, **extra) -> None:
    """Mark a phase in the state dict and persist."""
    if "phases" not in state[key]:
        state[key]["phases"] = {}
    entry = {"status": status, "updated_at": now_str()}
    entry.update(extra)
    state[key]["phases"][phase_name] = entry
    save_state(state)


def get_last_phase(state: dict, key: str) -> int:
    """Return the last completed phase number (0-indexed), or -1 if none."""
    phases = state.get(key, {}).get("phases", {})
    # Phase names: "0_discover", "1_assess", "2_listings", "3_details", "4_douyin", "5_wechat"
    completed = [int(p.split("_")[0]) for p, info in phases.items() if info.get("status") == "done"]
    return max(completed) if completed else -1


# ── Subprocess runner ─────────────────────────────────────────

def run_step(description: str, cmd: list[str], timeout: int = 7200) -> bool:
    """Run a subprocess step, streaming output live. Returns True on success."""
    print(f"\n{'='*60}")
    print(f"[{now_str()}] {description}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'='*60}", flush=True)
    try:
        env = {**__import__("os").environ, "PYTHONUNBUFFERED": "1"}
        result = subprocess.run(cmd, cwd=str(BASE_DIR), timeout=timeout, env=env)
        ok = result.returncode == 0
        print(f"  {'✓ Done' if ok else '✗ Failed'} (exit {result.returncode})", flush=True)
        return ok
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout ({timeout}s)", flush=True)
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}", flush=True)
        return False


# ── Phase 0: City discovery ───────────────────────────────────

def discover_city(city_name: str, city_slug: str) -> str | None:
    """
    Discover Anjuke base URL for a city.

    Returns the base community URL, or None if not found.
    """
    anjuke_url = f"https://{city_slug}.anjuke.com/community/"
    # Quick validation: the map lookup above provides the slug
    print(f"  City '{city_name}' → subdomain: {city_slug}.anjuke.com")
    print(f"  Base URL: {anjuke_url}")
    return anjuke_url


# ── Phase 1: Activity assessment ──────────────────────────────

def assess_district_activity(shangquan_file: Path) -> tuple[list[dict], list[dict]]:
    """
    Load shangquan file and split districts into core vs outskirts.

    Strategy: sort districts by number of shangquans (proxy for activity).
    Core = districts that together account for ~70% of total shangquan count.
    """
    data = json.loads(shangquan_file.read_text())
    districts = data.get("districts", {})

    # Build sorted list
    ranked = []
    for dist_name, dist_info in districts.items():
        sq_count = len(dist_info.get("shangquan", []))
        ranked.append({
            "name": dist_name,
            "slug": dist_info.get("slug", ""),
            "url": dist_info.get("url", ""),
            "shangquan_count": sq_count,
            "shangquan": dist_info.get("shangquan", []),
        })
    ranked.sort(key=lambda d: d["shangquan_count"], reverse=True)

    total_sq = sum(d["shangquan_count"] for d in ranked)
    cumulative = 0
    core = []
    outskirts = []
    for d in ranked:
        if cumulative < total_sq * 0.7 or len(core) < 3:
            core.append(d)
        else:
            outskirts.append(d)
        cumulative += d["shangquan_count"]

    print(f"\n  Total: {len(ranked)} districts, {total_sq} shangquans")
    print(f"  Core ({len(core)} districts): {[d['name'] for d in core]}")
    if outskirts:
        print(f"  Outskirts ({len(outskirts)} districts): {[d['name'] for d in outskirts]}")

    return core, outskirts


def _dry_assess(data: dict) -> tuple[list[dict], list[dict]]:
    """Dry-run version: sort districts by shangquan count and split."""
    ranked = []
    for dist_name, dist_info in data.get("districts", {}).items():
        sq_count = len(dist_info.get("shangquan", []))
        ranked.append({
            "name": dist_name,
            "slug": dist_info.get("slug", ""),
            "url": dist_info.get("url", ""),
            "shangquan_count": sq_count,
            "shangquan": dist_info.get("shangquan", []),
        })
    ranked.sort(key=lambda d: d["shangquan_count"], reverse=True)

    total_sq = sum(d["shangquan_count"] for d in ranked)
    cumulative = 0
    core = []
    outskirts = []
    for d in ranked:
        if cumulative < total_sq * 0.7 or len(core) < 3:
            core.append(d)
        else:
            outskirts.append(d)
        cumulative += d["shangquan_count"]

    print(f"\n  Total: {len(ranked)} districts, {total_sq} shangquans")
    print(f"  Core ({len(core)} districts): {[d['name'] for d in core]}")
    if outskirts:
        print(f"  Outskirts ({len(outskirts)} districts): {[d['name'] for d in outskirts]}")
    return core, outskirts


def generate_region_config(city: str, city_slug: str, district: dict) -> dict:
    """Auto-generate a region config entry for a discovered district."""
    district_slug = district["slug"]
    district_name = district["name"]
    region_id = f"{city_slug}_{district_slug}"

    return {
        "id": region_id,
        "name": district_name,
        "city": city,
        "province": "",  # Unknown for auto-discovered cities
        "anjuke_url": district["url"],
        "douyin_keywords": [
            f"{city}{district_name}买房", f"{city}{district_name}房产",
            f"{city}{district_name}新房", f"{city}{district_name}二手房",
            f"{city}{district_name}房价",
        ],
        "wechat_keywords": [
            f"{city} {district_name} 买房", f"{city} {district_name} 楼盘",
            f"{city} {district_name} 房价", f"{city} {district_name} 发展",
        ],
        "wechat_region_terms": [city, district_name],
        "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "最新房源", "好房推荐"],
        "gaode_city": city,
    }


# ── Main pipeline ─────────────────────────────────────────────

def run_onboard(
    city_name: str,
    city_slug: str | None = None,
    anjuke_url: str | None = None,
    include_all: bool = False,
    outskirts_only: bool = False,
    start_from: int = 0,
    dry_run: bool = False,
) -> None:
    create_tables()

    # Resolve city slug
    if not city_slug:
        city_slug = _ANJUKE_CITY_MAP.get(city_name)
        if not city_slug:
            print(f"Unknown city: {city_name}")
            print(f"Known cities: {', '.join(sorted(_ANJUKE_CITY_MAP.keys()))}")
            return

    state = init_state(city_name, city_slug)
    state_key = f"{city_name}_{city_slug}"

    # Check if we need to resume
    last_done = get_last_phase(state, state_key)
    if last_done >= 0 and start_from == 0:
        print(f"\n  📍 Resuming from phase {last_done + 1} (last completed: {last_done})")
        start_from = last_done + 1

    shangquan_file = BASE_DIR / "data" / f"shangquan_{city_slug}.json"

    print(f"\n{'='*60}")
    print(f"🏙  开城 Pipeline — {city_name} ({city_slug})")
    print(f"  Province-aware config not available for auto-discovered cities")
    print(f"{'='*60}")

    # ── Phase 0: Discover ──────────────────────────────────────
    if start_from <= 0:
        print(f"\n  ▶  Phase 0: 城市发现")
        if dry_run:
            print(f"     [DRY RUN] Would search Anjuke for '{city_name}' → {city_slug}.anjuke.com")
        else:
            resolved_url = anjuke_url or discover_city(city_name, city_slug)
            if not resolved_url:
                print(f"  ✗ Could not discover Anjuke URL for {city_name}")
                return

            # Run shangquan extraction
            ok = run_step(
                f"Phase 0: 商圈发现 ({city_name})",
                ["python3", "data/extract_shangquan.py", "--city", city_slug,
                 "--url", resolved_url],
                timeout=1800,
            )
            if ok:
                mark_phase(state, state_key, "0_discover", "done", url=resolved_url)
            else:
                mark_phase(state, state_key, "0_discover", "failed")
                print("  ⚠  Phase 0 had issues but continuing...")

    # ── Phase 1: Assess ────────────────────────────────────────
    core_districts = []
    outskirts_districts = []

    if start_from <= 1:
        print(f"\n  ▶  Phase 1: 活跃度评估")
        if not shangquan_file.exists():
            if dry_run:
                print(f"     [DRY RUN] shangquan file not yet created")
                print(f"     Run Phase 0 first to discover districts & shangquans")
                print(f"     Then re-run --dry-run to see the full execution plan")
            else:
                print(f"  ✗ No shangquan file: {shangquan_file}")
                print("  Run Phase 0 first.")
            return

        if dry_run:
            data = json.loads(shangquan_file.read_text())
            dist_count = len(data.get("districts", {}))
            print(f"     [DRY RUN] Would analyze {dist_count} districts, rank by activity")
            core_districts, outskirts_districts = _dry_assess(data)
            if outskirts_districts:
                print(f"     Outskirts (deferred): {[d['name'] for d in outskirts_districts]}")
        else:
            core_districts, outskirts_districts = assess_district_activity(shangquan_file)
            mark_phase(
                state, state_key, "1_assess", "done",
                core=[d["name"] for d in core_districts],
                outskirts=[d["name"] for d in outskirts_districts],
            )

    if outskirts_only:
        districts_to_scrape = outskirts_districts
        district_label = "outskirts"
    elif include_all:
        districts_to_scrape = core_districts + outskirts_districts
        district_label = "all"
    else:
        districts_to_scrape = core_districts
        district_label = "core"

    # When resuming from Phase 2+, load district list from shangquan file + pipeline state
    if not districts_to_scrape and start_from > 1:
        phase1_state = state.get(state_key, {}).get("phases", {}).get("1_assess", {})
        core_names = phase1_state.get("core", [])
        outskirts_names = phase1_state.get("outskirts", [])
        if outskirts_only:
            target_names = outskirts_names
            district_label = "outskirts"
        elif include_all:
            target_names = core_names + outskirts_names
            district_label = "all"
        else:
            target_names = core_names
            district_label = "core"
        if target_names and shangquan_file.exists():
            data = json.loads(shangquan_file.read_text())
            all_districts = data.get("districts", {})
            districts_to_scrape = sorted(
                [{"name": n, "slug": d.get("slug", ""), "url": d.get("url", ""),
                  "shangquan_count": len(d.get("shangquan", [])), "shangquan": d.get("shangquan", [])}
                 for n, d in all_districts.items() if n in target_names],
                key=lambda d: d["shangquan_count"], reverse=True,
            )
            print(f"\n  📍 Resumed — loaded {len(districts_to_scrape)} districts ({district_label}) from state")

    if not districts_to_scrape:
        # Fallback: load directly from shangquan file (no state, no Phase 1 filtering)
        if shangquan_file.exists():
            data = json.loads(shangquan_file.read_text())
            all_districts = [
                {"name": n, "slug": d.get("slug", ""), "url": d.get("url", ""),
                 "shangquan_count": len(d.get("shangquan", [])), "shangquan": d.get("shangquan", [])}
                for n, d in data.get("districts", {}).items()
            ]
            all_districts.sort(key=lambda d: d["shangquan_count"], reverse=True)

            if include_all or outskirts_only:
                # Need to re-assess to split core/outskirts
                total_sq = sum(d["shangquan_count"] for d in all_districts)
                cumulative = 0
                core = []
                outskirts = []
                for d in all_districts:
                    if cumulative < total_sq * 0.7 or len(core) < 3:
                        core.append(d)
                    else:
                        outskirts.append(d)
                    cumulative += d["shangquan_count"]
                if outskirts_only:
                    districts_to_scrape = outskirts
                    district_label = "outskirts"
                elif include_all:
                    districts_to_scrape = core + outskirts
                    district_label = "all"
                else:
                    districts_to_scrape = core
                    district_label = "core"
                print(f"\n  Re-assessed: {len(core)} core, {len(outskirts)} outskirts")
            else:
                # Default: core only (70% cumulative threshold)
                total_sq = sum(d["shangquan_count"] for d in all_districts)
                cumulative = 0
                core = []
                for d in all_districts:
                    if cumulative < total_sq * 0.7 or len(core) < 3:
                        core.append(d)
                    cumulative += d["shangquan_count"]
                districts_to_scrape = core
                district_label = "core"
                print(f"\n  Re-assessed: {len(core)} core districts (70% threshold)")

    print(f"\n  Scraping {len(districts_to_scrape)} districts ({district_label}):")
    for d in districts_to_scrape:
        print(f"    - {d['name']} ({d['shangquan_count']} shangquans)")

    # ── Write auto-generated region configs for subprocess scripts ──
    _auto_regions = {}
    for d in districts_to_scrape:
        _rc = generate_region_config(city_name, city_slug, d)
        _auto_regions[_rc["id"]] = _rc
    _auto_file = BASE_DIR / "data" / "auto_regions.json"
    _auto_file.write_text(json.dumps(_auto_regions, ensure_ascii=False, indent=2))
    print(f"  Auto-generated {len(_auto_regions)} region configs → {_auto_file}")

    # ── Phase 2-5: Scrape for each district ────────────────────
    for idx, district in enumerate(districts_to_scrape):
        region_config = generate_region_config(city_name, city_slug, district)
        region_id = region_config["id"]
        anjuke_region_url = region_config["anjuke_url"]

        # Delay between districts to avoid IP rate limiting
        if idx > 0:
            delay_s = random.uniform(30, 60)
            print(f"\n  ⏳ District cooldown: {delay_s:.0f}s...")
            time.sleep(delay_s)

        print(f"\n{'─'*50}")
        print(f"  [{idx+1}/{len(districts_to_scrape)}] {district['name']} (region_id={region_id})")
        print(f"{'─'*50}")

        # Phase 2: Listings
        if start_from <= 2:
            phase_key = f"2_listings_{region_id}"
            phase_state = state.get(state_key, {}).get("phases", {}).get(phase_key, {})
            if phase_state.get("status") == "done":
                print(f"    ⏭  Phase 2 (listings) already done, skipping")
            elif dry_run:
                print(f"    [DRY RUN] Would scrape listings for {region_id}")
            else:
                ok = run_step(
                    f"Phase 2: 列表采集 — {city_name} {district['name']}",
                    ["python3", "data/scrape_anjuke.py", "--region", region_id,
                     "--base-url", anjuke_region_url, "--listings-only", "--shangquan", "all",
                     "--chrome"],
                    timeout=7200,
                )
                mark_phase(state, state_key, phase_key, "done" if ok else "failed")

        # Phase 3: Details
        if start_from <= 3:
            phase_key = f"3_details_{region_id}"
            phase_state = state.get(state_key, {}).get("phases", {}).get(phase_key, {})
            if phase_state.get("status") == "done":
                print(f"    ⏭  Phase 3 (details) already done, skipping")
            elif dry_run:
                print(f"    [DRY RUN] Would scrape details for {region_id}")
            else:
                ok = run_step(
                    f"Phase 3: 详情补全 — {city_name} {district['name']}",
                    ["python3", "data/scrape_anjuke.py", "--region", region_id,
                     "--details-only", "--shangquan", "all", "--chrome"],
                    timeout=14400,
                )
                mark_phase(state, state_key, phase_key, "done" if ok else "failed")

        # Phase 4: Douyin
        if start_from <= 4:
            phase_key = f"4_douyin_{region_id}"
            phase_state = state.get(state_key, {}).get("phases", {}).get(phase_key, {})
            if phase_state.get("status") == "done":
                print(f"    ⏭  Phase 4 (douyin) already done, skipping")
            elif dry_run:
                print(f"    [DRY RUN] Would fetch Douyin for {region_id}")
            else:
                keywords = region_config["douyin_keywords"]
                ok = run_step(
                    f"Phase 4: 抖音内容 — {city_name} {district['name']}",
                    ["python3", "data/fetch_douyin.py", "--region", region_id,
                     "--keywords"] + keywords,
                    timeout=3600,
                )
                mark_phase(state, state_key, phase_key, "done" if ok else "failed")

        # Phase 5: WeChat
        if start_from <= 5:
            phase_key = f"5_wechat_{region_id}"
            phase_state = state.get(state_key, {}).get("phases", {}).get(phase_key, {})
            if phase_state.get("status") == "done":
                print(f"    ⏭  Phase 5 (wechat) already done, skipping")
            elif dry_run:
                print(f"    [DRY RUN] Would fetch WeChat for {region_id}")
            else:
                ok = run_step(
                    f"Phase 5: 微信内容 — {city_name} {district['name']}",
                    ["python3", "data/fetch_wechat.py", "--region", region_id],
                    timeout=7200,
                )
                mark_phase(state, state_key, phase_key, "done" if ok else "failed")

    # ── Summary ────────────────────────────────────────────────
    if not dry_run:
        conn = get_db()
        total_communities = sum(
            conn.execute(
                "SELECT COUNT(*) FROM communities WHERE region_id = ?",
                (generate_region_config(city_name, city_slug, d)["id"],),
            ).fetchone()[0]
            for d in districts_to_scrape
        )
        total_douyin = sum(
            conn.execute(
                "SELECT COUNT(*) FROM douyin_local_content WHERE region_id = ?",
                (generate_region_config(city_name, city_slug, d)["id"],),
            ).fetchone()[0]
            for d in districts_to_scrape
        )
        total_wechat = sum(
            conn.execute(
                "SELECT COUNT(*) FROM wechat_articles WHERE region_id = ?",
                (generate_region_config(city_name, city_slug, d)["id"],),
            ).fetchone()[0]
            for d in districts_to_scrape
        )
        conn.close()

        print(f"\n{'='*60}")
        print(f"🏙  开城完成 — {city_name} ({district_label})")
        print(f"  区域: {len(districts_to_scrape)} districts")
        print(f"  小区: {total_communities}  |  抖音: {total_douyin}  |  微信: {total_wechat}")
        print(f"{'='*60}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="City onboarding orchestrator — '开城' pipeline")
    parser.add_argument("--city", help="Chinese city name (e.g. 西安, 长沙)")
    parser.add_argument("--city-slug", help="Anjuke subdomain override (e.g. xian)")
    parser.add_argument("--anjuke-url", help="Anjuke community base URL (skip Phase 0)")
    parser.add_argument("--region", help="Existing region_id for partial re-run")
    parser.add_argument("--include-all", action="store_true", help="Scrape core + outskirts")
    parser.add_argument("--outskirts-only", action="store_true", help="Only scrape outskirts")
    parser.add_argument("--from-phase", type=int, default=0, help="Resume from phase N")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without executing")
    args = parser.parse_args()

    # Handle existing region re-run
    if args.region and not args.city:
        region = get_region(args.region)
        anjuke_url = region["anjuke_url"]
        city = region["city"]
        print(f"Re-running for existing region: {args.region} ({city} {region['name']})")
        # Generate a synthetic district entry
        district = {
            "name": region["name"],
            "slug": args.region.replace(f"{region.get('city_slug', '')}_", ""),
            "url": anjuke_url,
            "shangquan_count": 0,
            "shangquan": [],
        }
        state = init_state(city, args.region)
        state_key = f"{city}_{args.region}"

        if args.from_phase > 1:
            start_from = args.from_phase
        else:
            start_from = 0

        # Just run phases 2-5 for this single region
        # (City discovery & assessment already done)
        if start_from <= 2:
            ok = run_step(
                f"Phase 2: 列表采集 — {city} {district['name']}",
                ["python3", "data/scrape_anjuke.py", "--region", args.region,
                 "--base-url", anjuke_url, "--listings-only", "--shangquan", "all"],
                timeout=7200,
            )
            mark_phase(state, state_key, f"2_listings_{args.region}", "done" if ok else "failed")

        if start_from <= 3:
            ok = run_step(
                f"Phase 3: 详情补全 — {city} {district['name']}",
                ["python3", "data/scrape_anjuke.py", "--region", args.region,
                 "--details-only", "--shangquan", "all"],
                timeout=14400,
            )
            mark_phase(state, state_key, f"3_details_{args.region}", "done" if ok else "failed")

        if start_from <= 4:
            keywords = region["douyin_keywords"]
            ok = run_step(
                f"Phase 4: 抖音内容 — {city} {district['name']}",
                ["python3", "data/fetch_douyin.py", "--region", args.region,
                 "--keywords"] + keywords,
                timeout=3600,
            )
            mark_phase(state, state_key, f"4_douyin_{args.region}", "done" if ok else "failed")

        if start_from <= 5:
            ok = run_step(
                f"Phase 5: 微信内容 — {city} {district['name']}",
                ["python3", "data/fetch_wechat.py", "--region", args.region],
                timeout=7200,
            )
            mark_phase(state, state_key, f"5_wechat_{args.region}", "done" if ok else "failed")

        return

    # New city onboarding
    if not args.city:
        parser.print_help()
        print(f"\nKnown cities: {', '.join(sorted(_ANJUKE_CITY_MAP.keys()))}")
        return

    run_onboard(
        city_name=args.city,
        city_slug=args.city_slug,
        anjuke_url=args.anjuke_url,
        include_all=args.include_all,
        outskirts_only=args.outskirts_only,
        start_from=args.from_phase,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
