"""Central config for district-content-engine — multi-region edition."""

from __future__ import annotations

from pathlib import Path
import os

# ── Auto-load .env ──────────────────────────────────────────
_ENV_FILE = Path(__file__).resolve().parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            _key, _val = _key.strip(), _val.strip().strip('"').strip("'")
            if _key not in os.environ:
                os.environ[_key] = _val

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "district_content.db"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
SCRIPTS_DIR = BASE_DIR / "scripts"

# ── Region registry ───────────────────────────────────────────
# Add new cities here. region_id = city_district slug.

REGIONS = {
    "yangling": {
        "id": "yangling",
        "name": "杨陵区",
        "city": "咸阳",
        "province": "陕西",
        "anjuke_url": "https://xianyang.anjuke.com/community/yangling/",
        "douyin_keywords": [
            "杨凌买房", "杨凌房产", "杨凌新房", "杨凌二手房",
            "杨陵区买房", "杨陵区房产", "杨陵区新房", "杨陵区二手房",
        ],
        "wechat_keywords": [
            "杨凌 买房", "杨凌 楼盘 新房", "杨凌 房价 走势", "杨凌 房产 市场",
            "杨凌 城市规划", "杨凌 区域 发展", "杨凌 经济 产业", "杨凌 农业 科技 示范",
            "杨凌 企业 产业 园区", "杨凌 农高会", "杨凌 上合 农业 组织", "杨凌 自贸 保税",
            "西北农林科技大学 杨凌", "杨凌 人才 落户 政策", "杨凌 高铁 交通 规划",
            "杨凌 医院 医疗", "杨凌 万达 商业 配套", "杨凌 生活 环境 宜居", "杨凌 人口 发展",
        ],
        "wechat_region_terms": ["杨凌", "杨陵", "咸阳", "西农", "示范"],
        "wechat_exclude_terms": [
            "出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源",
            "杨凌在线-出售", "杨凌在线-出租", "最新房源", "好房推荐",
            "房价出炉.*你家", "最新小区房价",
        ],
        "gaode_city": "咸阳",
    },
    "datong_pingcheng": {
        "id": "datong_pingcheng",
        "name": "平城区",
        "city": "大同",
        "province": "山西",
        "anjuke_url": "https://datong.anjuke.com/community/pingcheng/",
        "douyin_keywords": [
            "大同买房", "大同房产", "大同新房", "大同二手房",
            "大同平城区", "大同御东买房", "大同古城买房",
        ],
        "wechat_keywords": [
            "大同 买房", "大同 平城区 楼盘", "大同 房价 走势", "大同 房产 市场",
            "大同 城市规划", "大同 御东 新区 发展", "大同 经济 产业",
            "大同 古城 保护 更新", "大同 文旅 发展", "大同 高铁 交通",
            "大同 医院 医疗", "大同 商业 配套 商圈", "大同 生活 环境 宜居",
            "大同 人口 发展", "大同 云冈 石窟 旅游",
        ],
        "wechat_region_terms": ["大同", "平城", "御东", "古城"],
        "wechat_exclude_terms": [
            "出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源",
            "最新房源", "好房推荐", "房价出炉.*你家", "最新小区房价",
        ],
        "gaode_city": "大同",
    },
    # ═══ 北京 2 区 ═══
    "beijing_haidian": {
        "id": "beijing_haidian",
        "name": "海淀",
        "city": "北京",
        "province": "北京",
        "anjuke_url": "https://beijing.anjuke.com/community/haidian/",
        "douyin_keywords": [
            "北京海淀买房", "北京海淀房产", "北京海淀新房", "北京海淀二手房",
            "北京海淀房价", "海淀学区房", "海淀楼盘", "海淀小区推荐",
            "中关村买房", "五道口买房", "西二旗买房", "上地买房",
        ],
        "wechat_keywords": [
            "北京 海淀 买房", "北京 海淀 楼盘 新房", "北京 海淀 房价 走势",
            "北京 海淀 房产 市场", "北京 海淀 城市规划", "北京 海淀 区域 发展",
            "北京 海淀 经济 产业", "北京 海淀 科技 互联网", "中关村 海淀 买房",
            "北京 海淀 学区 教育", "北京 海淀 地铁 交通 规划",
            "北京 海淀 医院 医疗", "北京 海淀 商业 配套 商圈",
            "北京 海淀 生活 环境 宜居", "北京 海淀 人口 发展",
            "北京 海淀 五道口 上地 西二旗 买房", "北京 海淀 清河 学院路 买房",
        ],
        "wechat_region_terms": ["北京", "海淀", "中关村", "五道口", "西二旗", "上地", "清河"],
        "wechat_exclude_terms": [
            "出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源",
            "最新房源", "好房推荐", "房价出炉.*你家", "最新小区房价",
        ],
        "gaode_city": "北京",
    },
    "beijing_chaoyang": {
        "id": "beijing_chaoyang",
        "name": "朝阳",
        "city": "北京",
        "province": "北京",
        "anjuke_url": "https://beijing.anjuke.com/community/chaoyang/",
        "douyin_keywords": [
            "北京朝阳买房", "北京朝阳房产", "北京朝阳新房", "北京朝阳二手房",
            "北京朝阳房价", "北京朝阳楼市", "望京买房", "国贸买房", "三里屯买房",
            "双井买房", "朝青买房", "东坝买房",
        ],
        "wechat_keywords": [
            "北京 朝阳 买房", "北京 朝阳 楼盘 新房", "北京 朝阳 房价 走势",
            "北京 朝阳 房产 市场", "北京 朝阳 城市规划", "北京 朝阳 区域 发展",
            "北京 朝阳 经济 产业", "北京 朝阳 CBD 国贸 买房",
            "北京 朝阳 望京 买房 发展", "北京 朝阳 三里屯 买房",
            "北京 朝阳 教育 学区", "北京 朝阳 地铁 交通 规划",
            "北京 朝阳 医院 医疗", "北京 朝阳 商业 配套 商圈",
            "北京 朝阳 生活 环境 宜居", "北京 朝阳 人口 发展",
            "北京 朝阳 东坝 常营 买房", "北京 朝阳 双井 劲松 买房",
        ],
        "wechat_region_terms": ["北京", "朝阳", "望京", "国贸", "CBD", "三里屯", "双井", "朝青"],
        "wechat_exclude_terms": [
            "出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源",
            "最新房源", "好房推荐", "房价出炉.*你家", "最新小区房价",
        ],
        "gaode_city": "北京",
    },
    # ═══ 北京 15 缺区 (待爬) ═══
    "beijing_xicheng": {"id": "beijing_xicheng", "name": "西城", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/xicheng/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_dongchenga": {"id": "beijing_dongchenga", "name": "东城", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/dongchenga/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_fengtai": {"id": "beijing_fengtai", "name": "丰台", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/fengtai/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_tongzhou": {"id": "beijing_tongzhou", "name": "通州", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/tongzhou/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_changping": {"id": "beijing_changping", "name": "昌平", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/changping/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_daxing": {"id": "beijing_daxing", "name": "大兴", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/daxing/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_shunyi": {"id": "beijing_shunyi", "name": "顺义", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/shunyi/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_fangshan": {"id": "beijing_fangshan", "name": "房山", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/fangshan/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_shijingshan": {"id": "beijing_shijingshan", "name": "石景山", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/shijingshan/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_miyun": {"id": "beijing_miyun", "name": "密云", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/miyun/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_huairou": {"id": "beijing_huairou", "name": "怀柔", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/huairou/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_mentougou": {"id": "beijing_mentougou", "name": "门头沟", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/mentougou/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_yanqing": {"id": "beijing_yanqing", "name": "延庆", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/yanqing/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_pinggua": {"id": "beijing_pinggua", "name": "平谷", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/pinggua/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    "beijing_beijingzhoubiana": {"id": "beijing_beijingzhoubiana", "name": "北京周边", "city": "北京", "province": "北京", "anjuke_url": "https://beijing.anjuke.com/community/beijingzhoubiana/", "douyin_keywords": [], "wechat_keywords": [], "wechat_region_terms": [], "wechat_exclude_terms": [], "gaode_city": "北京"},
    # ═══ 成都 25 区 ═══
    "chengdu_wuhou": {
        "id": "chengdu_wuhou", "name": "武侯", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/wuhou/",
        "douyin_keywords": ["成都武侯买房", "成都武侯房产", "成都武侯新房", "成都武侯二手房", "成都武侯房价"],
        "wechat_keywords": ["成都 武侯 买房", "成都 武侯 楼盘", "成都 武侯 房价", "成都 武侯 房产", "成都 武侯 规划", "成都 武侯 发展", "成都 武侯 交通", "成都 武侯 商业", "成都 武侯 配套", "成都 武侯 生活"],
        "wechat_region_terms": ["成都", "武侯"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_gaoxin": {
        "id": "chengdu_gaoxin", "name": "高新区", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/gaoxin/",
        "douyin_keywords": ["成都高新区买房", "成都高新区房产", "成都高新区新房", "成都高新区二手房", "成都高新区房价"],
        "wechat_keywords": ["成都 高新区 买房", "成都 高新区 楼盘", "成都 高新区 房价", "成都 高新区 房产", "成都 高新区 规划", "成都 高新区 发展", "成都 高新区 交通", "成都 高新区 商业", "成都 高新区 配套", "成都 高新区 生活"],
        "wechat_region_terms": ["成都", "高新区"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_chenghua": {
        "id": "chengdu_chenghua", "name": "成华", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/chenghua/",
        "douyin_keywords": ["成都成华买房", "成都成华房产", "成都成华新房", "成都成华二手房", "成都成华房价"],
        "wechat_keywords": ["成都 成华 买房", "成都 成华 楼盘", "成都 成华 房价", "成都 成华 房产", "成都 成华 规划", "成都 成华 发展", "成都 成华 交通", "成都 成华 商业", "成都 成华 配套", "成都 成华 生活"],
        "wechat_region_terms": ["成都", "成华"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_jinniu": {
        "id": "chengdu_jinniu", "name": "金牛", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/jinniu/",
        "douyin_keywords": ["成都金牛买房", "成都金牛房产", "成都金牛新房", "成都金牛二手房", "成都金牛房价"],
        "wechat_keywords": ["成都 金牛 买房", "成都 金牛 楼盘", "成都 金牛 房价", "成都 金牛 房产", "成都 金牛 规划", "成都 金牛 发展", "成都 金牛 交通", "成都 金牛 商业", "成都 金牛 配套", "成都 金牛 生活"],
        "wechat_region_terms": ["成都", "金牛"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_jinjiang": {
        "id": "chengdu_jinjiang", "name": "锦江", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/jinjiang/",
        "douyin_keywords": ["成都锦江买房", "成都锦江房产", "成都锦江新房", "成都锦江二手房", "成都锦江房价"],
        "wechat_keywords": ["成都 锦江 买房", "成都 锦江 楼盘", "成都 锦江 房价", "成都 锦江 房产", "成都 锦江 规划", "成都 锦江 发展", "成都 锦江 交通", "成都 锦江 商业", "成都 锦江 配套", "成都 锦江 生活"],
        "wechat_region_terms": ["成都", "锦江"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_piduqu": {
        "id": "chengdu_piduqu", "name": "郫都", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/piduqu/",
        "douyin_keywords": ["成都郫都买房", "成都郫都房产", "成都郫都新房", "成都郫都二手房", "成都郫都房价"],
        "wechat_keywords": ["成都 郫都 买房", "成都 郫都 楼盘", "成都 郫都 房价", "成都 郫都 房产", "成都 郫都 规划", "成都 郫都 发展", "成都 郫都 交通", "成都 郫都 商业", "成都 郫都 配套", "成都 郫都 生活"],
        "wechat_region_terms": ["成都", "郫都"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_longquanyi": {
        "id": "chengdu_longquanyi", "name": "龙泉驿", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/longquanyi/",
        "douyin_keywords": ["成都龙泉驿买房", "成都龙泉驿房产", "成都龙泉驿新房", "成都龙泉驿二手房", "成都龙泉驿房价"],
        "wechat_keywords": ["成都 龙泉驿 买房", "成都 龙泉驿 楼盘", "成都 龙泉驿 房价", "成都 龙泉驿 房产", "成都 龙泉驿 规划", "成都 龙泉驿 发展", "成都 龙泉驿 交通", "成都 龙泉驿 商业", "成都 龙泉驿 配套", "成都 龙泉驿 生活"],
        "wechat_region_terms": ["成都", "龙泉驿"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_xindu": {
        "id": "chengdu_xindu", "name": "新都", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/xindu/",
        "douyin_keywords": ["成都新都买房", "成都新都房产", "成都新都新房", "成都新都二手房", "成都新都房价"],
        "wechat_keywords": ["成都 新都 买房", "成都 新都 楼盘", "成都 新都 房价", "成都 新都 房产", "成都 新都 规划", "成都 新都 发展", "成都 新都 交通", "成都 新都 商业", "成都 新都 配套", "成都 新都 生活"],
        "wechat_region_terms": ["成都", "新都"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_qingyang": {
        "id": "chengdu_qingyang", "name": "青羊", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/qingyang/",
        "douyin_keywords": ["成都青羊买房", "成都青羊房产", "成都青羊新房", "成都青羊二手房", "成都青羊房价"],
        "wechat_keywords": ["成都 青羊 买房", "成都 青羊 楼盘", "成都 青羊 房价", "成都 青羊 房产", "成都 青羊 规划", "成都 青羊 发展", "成都 青羊 交通", "成都 青羊 商业", "成都 青羊 配套", "成都 青羊 生活"],
        "wechat_region_terms": ["成都", "青羊"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_shuangliu": {
        "id": "chengdu_shuangliu", "name": "双流", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/shuangliu/",
        "douyin_keywords": ["成都双流买房", "成都双流房产", "成都双流新房", "成都双流二手房", "成都双流房价"],
        "wechat_keywords": ["成都 双流 买房", "成都 双流 楼盘", "成都 双流 房价", "成都 双流 房产", "成都 双流 规划", "成都 双流 发展", "成都 双流 交通", "成都 双流 商业", "成都 双流 配套", "成都 双流 生活"],
        "wechat_region_terms": ["成都", "双流"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_wenjiang": {
        "id": "chengdu_wenjiang", "name": "温江", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/wenjiang/",
        "douyin_keywords": ["成都温江买房", "成都温江房产", "成都温江新房", "成都温江二手房", "成都温江房价"],
        "wechat_keywords": ["成都 温江 买房", "成都 温江 楼盘", "成都 温江 房价", "成都 温江 房产", "成都 温江 规划", "成都 温江 发展", "成都 温江 交通", "成都 温江 商业", "成都 温江 配套", "成都 温江 生活"],
        "wechat_region_terms": ["成都", "温江"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_tainfuxinqu": {
        "id": "chengdu_tainfuxinqu", "name": "天府新区", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/tainfuxinqu/",
        "douyin_keywords": ["成都天府新区买房", "成都天府新区房产", "成都天府新区新房", "成都天府新区二手房", "成都天府新区房价"],
        "wechat_keywords": ["成都 天府新区 买房", "成都 天府新区 楼盘", "成都 天府新区 房价", "成都 天府新区 房产", "成都 天府新区 规划", "成都 天府新区 发展", "成都 天府新区 交通", "成都 天府新区 商业", "成都 天府新区 配套", "成都 天府新区 生活"],
        "wechat_region_terms": ["成都", "天府新区"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_dujiangyan": {
        "id": "chengdu_dujiangyan", "name": "都江堰", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/dujiangyan/",
        "douyin_keywords": ["成都都江堰买房", "成都都江堰房产", "成都都江堰新房", "成都都江堰二手房", "成都都江堰房价"],
        "wechat_keywords": ["成都 都江堰 买房", "成都 都江堰 楼盘", "成都 都江堰 房价", "成都 都江堰 房产", "成都 都江堰 规划", "成都 都江堰 发展", "成都 都江堰 交通", "成都 都江堰 商业", "成都 都江堰 配套", "成都 都江堰 生活"],
        "wechat_region_terms": ["成都", "都江堰"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_chongzhoushi": {
        "id": "chengdu_chongzhoushi", "name": "崇州", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/chongzhoushi/",
        "douyin_keywords": ["成都崇州买房", "成都崇州房产", "成都崇州新房", "成都崇州二手房", "成都崇州房价"],
        "wechat_keywords": ["成都 崇州 买房", "成都 崇州 楼盘", "成都 崇州 房价", "成都 崇州 房产", "成都 崇州 规划", "成都 崇州 发展", "成都 崇州 交通", "成都 崇州 商业", "成都 崇州 配套", "成都 崇州 生活"],
        "wechat_region_terms": ["成都", "崇州"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_qingbaijiangqu": {
        "id": "chengdu_qingbaijiangqu", "name": "青白江", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/qingbaijiangqu/",
        "douyin_keywords": ["成都青白江买房", "成都青白江房产", "成都青白江新房", "成都青白江二手房", "成都青白江房价"],
        "wechat_keywords": ["成都 青白江 买房", "成都 青白江 楼盘", "成都 青白江 房价", "成都 青白江 房产", "成都 青白江 规划", "成都 青白江 发展", "成都 青白江 交通", "成都 青白江 商业", "成都 青白江 配套", "成都 青白江 生活"],
        "wechat_region_terms": ["成都", "青白江"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_jintangxian": {
        "id": "chengdu_jintangxian", "name": "金堂", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/jintangxian/",
        "douyin_keywords": ["成都金堂买房", "成都金堂房产", "成都金堂新房", "成都金堂二手房", "成都金堂房价"],
        "wechat_keywords": ["成都 金堂 买房", "成都 金堂 楼盘", "成都 金堂 房价", "成都 金堂 房产", "成都 金堂 规划", "成都 金堂 发展", "成都 金堂 交通", "成都 金堂 商业", "成都 金堂 配套", "成都 金堂 生活"],
        "wechat_region_terms": ["成都", "金堂"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_pengzhoushi": {
        "id": "chengdu_pengzhoushi", "name": "彭州", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/pengzhoushi/",
        "douyin_keywords": ["成都彭州买房", "成都彭州房产", "成都彭州新房", "成都彭州二手房", "成都彭州房价"],
        "wechat_keywords": ["成都 彭州 买房", "成都 彭州 楼盘", "成都 彭州 房价", "成都 彭州 房产", "成都 彭州 规划", "成都 彭州 发展", "成都 彭州 交通", "成都 彭州 商业", "成都 彭州 配套", "成都 彭州 生活"],
        "wechat_region_terms": ["成都", "彭州"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_qionglaishi": {
        "id": "chengdu_qionglaishi", "name": "邛崃市", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/qionglaishi/",
        "douyin_keywords": ["成都邛崃市买房", "成都邛崃市房产", "成都邛崃市新房", "成都邛崃市二手房", "成都邛崃市房价"],
        "wechat_keywords": ["成都 邛崃市 买房", "成都 邛崃市 楼盘", "成都 邛崃市 房价", "成都 邛崃市 房产", "成都 邛崃市 规划", "成都 邛崃市 发展", "成都 邛崃市 交通", "成都 邛崃市 商业", "成都 邛崃市 配套", "成都 邛崃市 生活"],
        "wechat_region_terms": ["成都", "邛崃市"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_gaoxinxiqu": {
        "id": "chengdu_gaoxinxiqu", "name": "高新西区", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/gaoxinxiqu/",
        "douyin_keywords": ["成都高新西区买房", "成都高新西区房产", "成都高新西区新房", "成都高新西区二手房", "成都高新西区房价"],
        "wechat_keywords": ["成都 高新西区 买房", "成都 高新西区 楼盘", "成都 高新西区 房价", "成都 高新西区 房产", "成都 高新西区 规划", "成都 高新西区 发展", "成都 高新西区 交通", "成都 高新西区 商业", "成都 高新西区 配套", "成都 高新西区 生活"],
        "wechat_region_terms": ["成都", "高新西区"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_xinjinxian": {
        "id": "chengdu_xinjinxian", "name": "新津", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/xinjinxian/",
        "douyin_keywords": ["成都新津买房", "成都新津房产", "成都新津新房", "成都新津二手房", "成都新津房价"],
        "wechat_keywords": ["成都 新津 买房", "成都 新津 楼盘", "成都 新津 房价", "成都 新津 房产", "成都 新津 规划", "成都 新津 发展", "成都 新津 交通", "成都 新津 商业", "成都 新津 配套", "成都 新津 生活"],
        "wechat_region_terms": ["成都", "新津"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_dayixian": {
        "id": "chengdu_dayixian", "name": "大邑", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/dayixian/",
        "douyin_keywords": ["成都大邑买房", "成都大邑房产", "成都大邑新房", "成都大邑二手房", "成都大邑房价"],
        "wechat_keywords": ["成都 大邑 买房", "成都 大邑 楼盘", "成都 大邑 房价", "成都 大邑 房产", "成都 大邑 规划", "成都 大邑 发展", "成都 大邑 交通", "成都 大邑 商业", "成都 大邑 配套", "成都 大邑 生活"],
        "wechat_region_terms": ["成都", "大邑"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_cdpujiangxian": {
        "id": "chengdu_cdpujiangxian", "name": "蒲江", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/cdpujiangxian/",
        "douyin_keywords": ["成都蒲江买房", "成都蒲江房产", "成都蒲江新房", "成都蒲江二手房", "成都蒲江房价"],
        "wechat_keywords": ["成都 蒲江 买房", "成都 蒲江 楼盘", "成都 蒲江 房价", "成都 蒲江 房产", "成都 蒲江 规划", "成都 蒲江 发展", "成都 蒲江 交通", "成都 蒲江 商业", "成都 蒲江 配套", "成都 蒲江 生活"],
        "wechat_region_terms": ["成都", "蒲江"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_chengduzhoubian": {
        "id": "chengdu_chengduzhoubian", "name": "成都周边", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/chengduzhoubian/",
        "douyin_keywords": ["成都周边买房", "成都周边房产", "成都周边新房", "成都周边二手房", "成都周边房价"],
        "wechat_keywords": ["成都 周边 买房", "成都 周边 楼盘", "成都 周边 房价", "成都 周边 房产", "成都 周边 规划", "成都 周边 发展", "成都 周边 交通", "成都 周边 商业", "成都 周边 配套", "成都 周边 生活"],
        "wechat_region_terms": ["成都", "周边"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_cdjianyang": {
        "id": "chengdu_cdjianyang", "name": "简阳", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/cdjianyang/",
        "douyin_keywords": ["成都简阳买房", "成都简阳房产", "成都简阳新房", "成都简阳二手房", "成都简阳房价"],
        "wechat_keywords": ["成都 简阳 买房", "成都 简阳 楼盘", "成都 简阳 房价", "成都 简阳 房产", "成都 简阳 规划", "成都 简阳 发展", "成都 简阳 交通", "成都 简阳 商业", "成都 简阳 配套", "成都 简阳 生活"],
        "wechat_region_terms": ["成都", "简阳"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    "chengdu_dongbuxinqu": {
        "id": "chengdu_dongbuxinqu", "name": "东部新区", "city": "成都", "province": "四川",
        "anjuke_url": "https://chengdu.anjuke.com/community/dongbuxinqu/",
        "douyin_keywords": ["成都东部新区买房", "成都东部新区房产", "成都东部新区新房", "成都东部新区二手房", "成都东部新区房价"],
        "wechat_keywords": ["成都 东部新区 买房", "成都 东部新区 楼盘", "成都 东部新区 房价", "成都 东部新区 房产", "成都 东部新区 规划", "成都 东部新区 发展", "成都 东部新区 交通", "成都 东部新区 商业", "成都 东部新区 配套", "成都 东部新区 生活"],
        "wechat_region_terms": ["成都", "东部新区"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "成都",
    },
    # ═══ 燕郊/北三县 (廊坊) ═══
    "langfang_sanhe": {
        "id": "langfang_sanhe", "name": "三河(燕郊)", "city": "廊坊", "province": "河北",
        "anjuke_url": "https://langfang.anjuke.com/community/sanhe/",
        "douyin_keywords": ["燕郊买房", "燕郊房产", "燕郊新房", "燕郊二手房", "燕郊房价", "三河买房", "北三县买房"],
        "wechat_keywords": ["燕郊 买房", "燕郊 楼盘", "燕郊 房价", "燕郊 房产", "燕郊 规划", "燕郊 地铁", "燕郊 通勤", "燕郊 发展", "北三县 买房", "三河 房产"],
        "wechat_region_terms": ["燕郊", "三河", "北三县", "廊坊"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "廊坊",
    },
    "langfang_dachang": {
        "id": "langfang_dachang", "name": "大厂", "city": "廊坊", "province": "河北",
        "anjuke_url": "https://langfang.anjuke.com/community/dachang/",
        "douyin_keywords": ["大厂买房", "大厂房产", "大厂新房", "大厂二手房", "大厂房价", "北三县买房"],
        "wechat_keywords": ["大厂 买房", "大厂 楼盘", "大厂 房价", "大厂 房产", "大厂 规划", "北三县 买房", "大厂 潮白新城"],
        "wechat_region_terms": ["大厂", "北三县", "潮白", "廊坊"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "廊坊",
    },
    "langfang_xianghe": {
        "id": "langfang_xianghe", "name": "香河", "city": "廊坊", "province": "河北",
        "anjuke_url": "https://langfang.anjuke.com/community/xianghe/",
        "douyin_keywords": ["香河买房", "香河房产", "香河新房", "香河二手房", "香河房价", "北三县买房"],
        "wechat_keywords": ["香河 买房", "香河 楼盘", "香河 房价", "香河 房产", "香河 规划", "北三县 买房"],
        "wechat_region_terms": ["香河", "北三县", "廊坊"], "wechat_exclude_terms": ["出售房屋信息展示", "出租房源信息展示", "精选二手房在售房源", "最新房源", "好房推荐"],
        "gaode_city": "廊坊",
    },
}

DEFAULT_REGION = "yangling"


def get_region(region_id: str | None = None) -> dict:
    """Return region config dict. Falls back to DEFAULT_REGION if None.

    Checks REGIONS dict first, then auto-generated regions from data/auto_regions.json.
    """
    key = region_id or DEFAULT_REGION
    if key in REGIONS:
        return REGIONS[key]
    # Check auto-generated regions file (written by onboard_city.py)
    _auto_file = BASE_DIR / "data" / "auto_regions.json"
    if _auto_file.exists():
        import json as _json
        _auto = _json.loads(_auto_file.read_text(encoding="utf-8"))
        if key in _auto:
            return _auto[key]
    raise KeyError(f"Unknown region '{key}'. Available: {list(REGIONS.keys())} + {list((_json.loads(_auto_file.read_text()) if _auto_file.exists() else {}).keys()) if _auto_file.exists() else 'none'}")


def get_region_name(region_id: str | None = None) -> str:
    return get_region(region_id)["name"]


def get_region_city(region_id: str | None = None) -> str:
    return get_region(region_id)["city"]


def get_region_province(region_id: str | None = None) -> str:
    return get_region(region_id)["province"]


def get_douyin_keywords(region_id: str | None = None) -> list[str]:
    return get_region(region_id)["douyin_keywords"]


# ── API keys ──────────────────────────────────────────────────

GAODE_KEY = os.getenv("GAODE_KEY", "")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY", "")
BAILIAN_KEY = os.getenv("BAILIAN_KEY", "")
DEEPSEEK_MODEL = "deepseek/deepseek-chat"

# ── Scraper settings ──────────────────────────────────────────

PAGE_DELAY_MIN_MS = 5_000
PAGE_DELAY_MAX_MS = 12_000
DETAIL_DELAY_MIN_MS = 5_000
DETAIL_DELAY_MAX_MS = 12_000
RPM_SOFT_CAP = 2             # Soft rate limit: requests per minute (lower = more human)
RPM_HARD_CAP = 4             # Hard rate limit
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
