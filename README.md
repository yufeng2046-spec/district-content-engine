# District Content Engine

自动化房产视频脚本生成系统。从网络公开数据（安居客+高德+抖音）采集楼盘信息，通过 LLM 生成爆款风格的房产探盘/口播脚本。

## 区域覆盖

| 区域 | 小区数 | 数据完整度 | 状态 |
|------|--------|-----------|------|
| 咸阳·杨陵区 | 149 | ≥8/10字段 72% | 完成 |

## 项目结构

```
├── config.py              # API keys, 区域配置, 爬虫参数
├── generate.py            # 入口：python generate.py --track A --community <id>
├── db/
│   ├── schema.py          # 建表（communities, community_poi, generated_scripts）
│   └── connection.py      # SQLite 连接
├── data/
│   ├── scrape_anjuke.py   # 安居客爬虫（列表+详情+分页）
│   ├── gaode_client.py    # 高德 API 封装（周边搜索/步行距离）
│   ├── enrich_gaode.py    # POI 富化流水线
│   └── fetch_douyin.py    # 抖音本地内容采集
├── agents/
│   ├── researcher.py      # 拼装研究简报
│   ├── writer.py          # LLM 脚本生成（双轨）
│   ├── editor.py          # 合规审查 + 去AI味
│   └── llm.py             # DeepSeek API 封装
├── prompts/
│   ├── track_a.txt        # 小区探盘提示词（120-150秒）
│   ├── track_b.txt        # 区域口播提示词（80-120秒）
│   └── editor.txt         # 终审编辑提示词
└── output/
    ├── yangling_communities_v2.csv  # 杨凌149小区全量数据
    └── *.md               # 生成的脚本
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 采集数据

```bash
# 安居客（先手动过验证码）
PYTHONPATH=. python3 data/scrape_anjuke.py --login   # 打开可见浏览器，过验证码
PYTHONPATH=. python3 data/scrape_anjuke.py           # 无头模式爬取

# 高德 POI 富化（需要 API Key）
export GAODE_KEY=your_key
PYTHONPATH=. python3 data/enrich_gaode.py

# 抖音本地内容
PYTHONPATH=. python3 data/fetch_douyin.py
```

### 3. 生成脚本

```bash
# 单小区探盘
PYTHONPATH=. python3 generate.py --track A --community xianyang_yangling_1073152

# 列出所有可用小区
PYTHONPATH=. python3 generate.py --track A --list

# 区域口播
PYTHONPATH=. python3 generate.py --track B
```

## 安居客反爬策略

- **验证码处理**：首次运行 `--login` 用可见浏览器手动过验证码，保存 `storage_state`
- **风控阈值**：请求频率 ≤ 8次/分钟（间隔 ≥ 6秒）不触发验证码
- **Stealth JS**：覆盖 navigator.webdriver、plugins、languages 等指纹
- **IP 限流**：同一 IP 连续 46+ 次快速请求后触发验证码，降低频率后可通过

## 数据来源

- **安居客**：小区基础数据（价格/户型/物业/年代）
- **高德地图**：周边配套 POI（学校/商业/交通/公园）
- **抖音**：本地房产内容（吐槽/价格讨论/社区提及）

## License

MIT
