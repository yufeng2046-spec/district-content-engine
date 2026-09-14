# 安居客全国小区数据引擎

> **目标**: 覆盖全国 ~100 重点城市的小区数据，含详情、坐标、周边配套、价格趋势、业主评价，用于 LLM 自动化写探盘文案。
>
> **定位(2026-09-07 锁定)**: 全国**二手房社区**数据平台, 采集原则 = **应爬尽爬**(广度×深度爬满)。❌ huxingtu 户型永久不做; ❌ 新房 newhouse 本轮不做。
>
> **最后更新**: 2026-09-07（B4 商圈重爬 + B1 详情补 + 全部 BLOCK 清零）
>
> **决策/规划文档**: 最新待办见 **[TODO.md](TODO.md)**(唯一权威) | 全案评估/风险难点见 **[PROJECT_REVIEW.md](PROJECT_REVIEW.md)**

---

## 📊 最新数据现状 (2026-09-07)

```
总小区: 125,525   详情: 100.00%(剩雁荡大厦 1)   空名称: 0   零坐标: 1
缺商圈: 1,006(含 langfang 750 + yangling 149 诚实空值; 有商圈城实缺 107)
BLOCK: 0   商圈表: 1,708   9 城 (shanghai 37K/chengdu 24K/beijing 22K/guangzhou 20K/shenzhen 13K/xa 7.2K/datong/langfang/yangling)
```

详细分城/字段填充率/历史经过见 PROJECT_REVIEW.md。

---

## 🚀 新会话快速上手

```bash
# 1. 确认 DB 状态
PYTHONPATH=. python3 -c "
from db.connection import get_db
conn = get_db()
total = conn.execute('SELECT COUNT(*) FROM communities').fetchone()[0]
detail = conn.execute('SELECT COUNT(*) FROM communities WHERE detail_scraped_at IS NOT NULL').fetchone()[0]
null_sq = conn.execute('SELECT COUNT(*) FROM communities WHERE shangquan_id IS NULL').fetchone()[0]
print(f'小区: {total:,} | 详情: {detail:,} ({detail/total*100:.1f}%) | 缺商圈: {null_sq:,}')
# Per-city breakdown
for row in conn.execute('''SELECT substr(region_id,1,instr(region_id||\"_\",\"_\")-1) as city,
    COUNT(DISTINCT region_id) as dists, COUNT(*) as cnt
    FROM communities GROUP BY 1 ORDER BY cnt DESC''').fetchall():
    print(f'  {row[0]:12s}: {row[1]:>2}区 {row[2]:>6,}小区')
conn.close()
"

# 2. 确认会话状态 (per-city state files)
python3 session_factory.py --show-sessions

# 3. 确认 CubeMini 状态
python3 sync_state_to_cubemini.py --no-sync

# 4. 确认备份状态
ls -lh backups/ && echo '---' && crontab -l | grep backup
```

---

## 📊 当前数据状态 (2026-08-06)

### 地理层级（已建立）

```
省 provinces (34) → 城市 cities (338) → 区 districts (118) → 商圈 shangquans (1,708) → 小区 communities (47,968)
```

| 表 | 行数 | 说明 |
|----|------|------|
| provinces | 34 | 标准 GB/T 2260 省级行政区 + 港澳台 |
| cities | 338 | **物理地级市**（334 地级 + 4 直辖市），重分类修复了 15 个自治州误分类 |
| anjuke_county_map.json | 335 | 县级子域参考文件（昆山/香河等，含父地级市），真爬到时实例化为 district |
| districts | 118 | 区县目录，district_id = slug 格式，挂到城市/省 |
| shangquans | 1,708 | 商圈，shangquan_id = `{city}_{district_slug}_{sq_slug}` |
| communities | 47,968 | 已回填 city_id/province_id (100%) |

### 小区数据

```
城市           总小区    备注
北京            21,839   ← ✅ 17/17 区全覆盖
成都            17,888   ← ✅ 25 区
西安             4,299   ← ✅ 8 区
上海             1,818
廊坊               750   (无商圈城市, shangquan 应为 NULL)
大同               725
广州               250
深圳               250
咸阳(杨凌)          149   (杨凌是咸阳的区, 非独立城市)
─────────────────────────
合计            47,968   详情 100% | 零坐标 0 | 省市 100% | 商圈 44,871 非空
```

**⚠️ 商圈 3,097 条为 NULL（诚实空值）**：其中 899（廊坊+杨凌）本就没有商圈（安居客无此层级）；2,198 是修复跨城 bug 后清掉的错误值，**待按商圈重爬回填**（listings-only 即可）。

---

## 🗺️ 数据库结构

### communities 表 (核心 — 47,968 行)

**地理定位**

| 字段 | 类型 | 说明 | 填充率 |
|------|------|------|--------|
| community_id | TEXT PK | `{城市}_{区}_{anjuke_id}` | 100% |
| province_id | TEXT FK | 省 | 100% |
| city_id | TEXT FK | 地级市 | 100% |
| district_id | TEXT | 区县（待选项1迁移补充） | — |
| shangquan_id | TEXT FK | 所属商圈（无商圈=NULL） | 93.5% |
| region_id | TEXT | 爬取桶（运营用） | 100% |
| coordinate_lng/lat | REAL | 经纬度 | 97.8% |

**基础/价格/建筑**

| 字段 | 类型 | 说明 | 填充率 |
|------|------|------|--------|
| name / address | TEXT | 名称/地址 | 100% |
| avg_price | REAL | 均价 (元/㎡) | 99.8% |
| year_built | INTEGER | 建成年份(首个) | 78.7% |
| total_units | INTEGER | 总户数 | 78.1% |
| floor_area_ratio | REAL | 容积率 | 79.0% |
| green_ratio | REAL | 绿化率 | 76.3% |
| parking_ratio | TEXT | 停车位 | 48.0% |
| building_types | TEXT | 建筑类型 JSON数组 | 82.0% |
| developer | TEXT | 开发商 | 97.8% |
| property_mgmt | TEXT | 物业公司 | 97.6% |
| property_fee | REAL | 物业费 | 72.6% |
| on_sale_count / on_rent_count / listing_count | INT | 在售/在租/挂牌 | 46-61% |

**JSON 详情字段**

| 字段 | 说明 | 填充率 |
|------|------|--------|
| surrounding_json | 周边 7 类: bus/metro/school/shopping/hospital/bank/dining, 每类 `[{name,distance,extra}]` | 95.3% |
| price_trend_json | `{current_price, monthly_change_pct, shangquan_price, monthly_prices:[{month,price}]}` | 93.2% |
| community_review | `[{author,date,pros}]` + `[{type:"qa",question,answers}]` | 64.9% |
| property_basic_json | 同页基本信息补充: `{property_type, ownership, rights_years, building_area, heating, water_electric, parking_fee, parking_mgmt_fee, years_built[]}` | 未来爬取 |
| community_interpretation_json | 小区解读: `{transport, layout, facilities, life_support, shortcomings}` | 未来爬取 |
| huxingtu_json | 户型: `[{type,rooms,halls,area,image}]` (独立页爬取) | 未来爬取 |

> ⚠️ 后 3 个 JSON 字段已加列 + 爬虫已支持提取，但**存量数据未补爬**（见 TODO）。

### 其他表

| 表 | 行数 | 说明 |
|----|------|------|
| districts | 114 | 区级地理层级 (7城) |
| shangquans | 1,708 | 商圈→安居客URL映射 |
| community_poi | 10,188 | 标准化POI (仅451小区) |
| generated_scripts | 60 | 已生成的探盘文案 |

### 商圈 JSON 文件

`data/shangquan_{city}.json` — `discover_shangquan.py` 的输出。每个文件包含该城市所有区→商圈的映射和安居客 URL。

---

## 🐛 经验教训 (踩坑记录)

### 1. 安居客有两套 URL 格式

```
旧版: /community/chaoyang/wangjing/     (早期北京/成都/西安)
新版: /community/pudong-q-babaiban/     (上海/广州/深圳，北京也已升级)
                                       ↑ -q- 分隔符!
```

所有 URL 解析正则必须同时匹配两种格式。

### 2. 商圈发现会把筛选器当作"商圈"

```python
# ❌ /community/pudong/m250/ → m250 被当作商圈名
# ✅ m250 = 价格筛选参数 (m=价格, f=房龄, s=地铁, w=物业, o=排序, p=分页)
```

**修复**: `discover_shangquan.py` 加了语义校验——URL slug 不能以单字母+数字开头，链接文本不能含"万/年/地铁/物业"等关键词。

### 3. 翻页限制 → 必须按商圈爬，不按区爬

```
按区爬: 朝阳 2,459 小区 → 99页 → ⚠️ 安居客翻页上限 → 尾部丢失
按商圈爬: 朝阳 76 商圈 × ~32 小区/商圈 = ~2页/商圈 → ✅ 完整
```

**教训: 永远按商圈维度爬取。商圈是最小单元，每个商圈的小区数远小于翻页上限。**

### 4. 详情页"所属商圈"被丢弃了

```python
# scrape_anjuke.py line 1001:
"building_types": r"建筑类型\s*(.+?)(?:所属商圈|统一供暖|供水|$)",
#                                          ↑ 把"所属商圈"当截断符
#                                          后面的 "CBD" 被丢弃!
```

需加正则提取 `所属商圈\s*(.+)`。

### 5. 易盾验证码不能靠 VL 模型自动过

类型: 文字顺序、滑块、点击。VL OCR 对滑块和点击型无效。

**方案**:
- 本地: 可见浏览器 → 暂停 → 人工过
- CubeMini: 本地导出 cookie → SCP → 零验证码启动
- 飞书通知 webhook: `https://open.feishu.cn/open-apis/bot/v2/hook/bb7f59f4-9b6e-444f-aea6-f8b2c6397adc`

### 6. Cookie/会话持久化是核心

用 Playwright 的 `storage_state` (不是手动 cookie)——保存完整浏览器状态含 localStorage、indexedDB。每次 scraping session 结束后保存，下次加载继续用。

### 7. 人类行为模拟 (`_humanize()`)

```python
await _humanize(page, intensity="medium")
# 随机滚动 + 鼠标移动 + hover + 停顿
```

每个页面加载后必须调用。风控参数 (`config.py`): 页间延迟 5-12s, 详情延迟 5-12s, RPM 软上限 2, 硬上限 4。

### 8. 双 IP 策略 (2026-07-23 重写)

**核心洞察**: 安居客验证码风险 = f(会话质量, IP信誉, 地理邻近, 请求模式)。CubeMini 是更优的爬虫机器(住宅IP)，但不能创建会话(headless无法过验证码)。本地 Mac 是"会话工厂"(可见浏览器可人工过码)。

**新架构 — 会话工厂 + 双机并行**:

```
本地 Mac (北京IP, visible)           CubeMini (张家口IP, headless)
    │                                     │
    ├─ session_factory.py                 │
    │  ├─ 打开可见Chrome                   │
    │  ├─ 逐个城市登录 anjuke               │
    │  ├─ 人工过验证码 (1次/城市)            │
    │  └─ 保存 anjuke_state_{city}.json   │
    │                                     │
    ├─ sync_state_to_cubemini.py ──────→  ├─ 拿到所有城市的独立 state
    │                                     │
    ├─ 爬北京各區 (可见, 可中途过码)          ├─ 爬其他城市 (headless, 住宅IP)
    │  --region beijing_dongcheng          │  --region shanghai_pudong
    │  --shangquan all --show              │  --shangquan all
    │                                     │
    └─ 两者同时工作，互不干扰                 └─ 验证码→保存进度退出→等下次sync
```

**关键设计**:
- **Per-city state 隔离**: `anjuke_state_{city}.json` — 每个城市独立会话，解决跨城 cookie 失效
- **会话工厂**: 20分钟创建 5-10 个城市的有效会话 → CubeMini 可以跑数天
- **城市→IP 路由**: 北京→本地Mac (地理匹配), 其他→CubeMini (住宅IP低风控)
- **并行爬取**: 两台机器同时跑不同城市，吞吐量翻倍

### 9. CubeMini 连接

- 跳板机: `frank@120.12.17.243:2222`
- 目标: `frank@192.168.31.101`
- 工具: `competitor-report/ssh_cubemini.py`
- Python: `/home/frank/crawler-venv/bin/python3`
- 浏览器: `/usr/bin/chromium-browser`
- DB: `/home/frank/district-content-engine/district_content.db`

**部署注意**: 必须同步整个项目目录（含 `config.py`、`db/` 模块）。改代码后必须 `pkill -f cube_expand.py` 重启进程。

### 10. 备份是必须的

- 本地: `backups/` 目录, 每日 02:07 (cron)
- CubeMini: `/home/frank/backups/`
- 脚本: `./backup_db.sh` → 完整性检查 → 本地 cp → SFTP 推 CubeMini
- 保留 7 天滚动

### 11. CubeMini headless 必须有有效 cookie

住宅IP低风控 ≠ 零验证码。Cookie过期后 headless 秒触发验证码，且无法人工过。

**关键**: CubeMini 的 `anjuke_state.json` 必须在本地 interactive browser 过完验证码后立即同步过去。State 文件的生命周期取决于浏览器活跃度——本地 Mac 一直开着 Chrome 爬，session 保持有效；CubeMini 拿到同步的 state 后才能无验证码跑。

### 12. 定期保存状态 + 断点续跑

`scrape_all_shangquan()` 现在：
- 每个商圈完成后保存 `anjuke_state.json` (crash安全 + CubeMini可同步)
- 写 `data/progress_{region_id}.json` 记录已完成的商圈
- 重启时自动跳过已完成的商圈
- Headless 连续 3 次验证码阻塞 → 保存进度退出 (不浪费资源等超时)

### 13. 双机协作 pipeline

```
本地 Mac (visible Chrome)           CubeMini (headless)
    │                                    │
    ├─ 过验证码 (人工)                     │
    ├─ 爬北京西城...                       │
    ├─ 商圈完成后保存 state               │
    │                                    │
    ├─ sync_state_to_cubemini.py ──────→ ├─ 拿到新鲜 state
    │                                    ├─ 住宅IP大量跑
    │                                    └─ 无验证码！
```

### 14. 验证码通知区分来源

飞书通知里的截屏路径可以区分是哪台机器:
- `/tmp/tmp*.png` → 本地 Mac (visible browser, 去窗口解)
- CubeMini 上的路径 → headless (无法人工解, 需要同步 cookie)

### 15. JSON key ≠ 中文名

shangquan JSON 的 district key 是**英文 slug** (`xicheng`), 不是 config 的 `name` 字段 (`"西城"`)。`scrape_all_shangquan()` 的 district filter 现在用 `region_id` 提取 slug 来匹配。

### 16. Per-city 会话隔离

单个 `anjuke_state.json` 在不同城市间共享会导致 session 污染。虽然 `.anjuke.com` 是 wildcard domain cookie，但 localStorage、indexedDB、以及某些反爬 token 是 per-subdomain 的。

**解决**: `anjuke_state_{city}.json` — 每个城市独立的 storage state。`scrape_anjuke.py` 从 `region_id` 自动提取 city 并使用对应的 state 文件。`--state` 参数可手动指定。

```
anjuke_state.json          ← 旧版全局 (向后兼容 fallback)
anjuke_state_beijing.json  ← 北京专用
anjuke_state_shanghai.json ← 上海专用
anjuke_state_chengdu.json  ← 成都专用
...
```

### 17. 会话工厂模式

CubeMini 是更优的爬虫机器（住宅IP）但无法创建会话（headless）。本地 Mac 可以创建会话（visible browser + 人工过码）但 IP 信誉较低。

**模式**: 本地 Mac 作为"会话工厂"，用 `session_factory.py` 打开可见 Chrome，逐个城市登录安居客，人工过一次验证码，导出 per-city state。然后 `sync_state_to_cubemini.py` 将所有 state 同步到 CubeMini。CubeMini 拿到新鲜会话后可以 headless 跑数天。

**操作**: `python3 session_factory.py` → 20分钟创建 5-10 城会话 → `python3 sync_state_to_cubemini.py` → CubeMini 开工。

### 18. IP 隔离是铁律 — 不能跨机器共享 Session

安居客验证码机制对 **IP 突变** 极其敏感。本地 Mac（北京 IP）创建的 session sync 到 CubeMini（张家口 IP）→ 秒触发验证码。即使 session 只创建了 8 分钟、从未被爬取使用过，IP 不同就是不行。

**结论**: 每台机器必须在**自己的 IP 上**创建 session。`session_factory.py` 只能为本地 Mac 创建会话。CubeMini 必须自己在张家口 IP 上登录。

### 19. 持久化 Profile 适合登录，State 文件适合爬取

CubeMini 的 `chrome_profile_cube/` 持久化 Chrome profile 积累了数周的浏览器指纹和会话信誉。这个 profile 访问安居客时**验证码会自动清除**（30 秒内），因为浏览器身份被识别为"老用户"。

但同样的 profile 用在爬虫中会出问题：爬虫频繁的 launch/exit 循环会污染 profile（部分保存的 blocked state 覆盖了有效 session）。

**正确用法**:
- **登录阶段**: 使用 `--profile`（持久化 profile），验证码自动清除
- **爬取阶段**: 登录成功后保存 `anjuke_state.json`，爬虫**不使用** `--profile`，改用 state 文件

```
登录:  --login --manual --xvfb --profile chrome_profile_cube
      → 验证码自动清除 → 保存 anjuke_state.json
爬取:  --xvfb  (不带 --profile)
      → 从 anjuke_state.json 加载 session → 稳定爬取
```

### 20. CubeMini 启动流程（已验证）

```bash
# 步骤 1: 在 CubeMini 上登录 Beijing 站（持久化 profile，验证码自动清除）
DISPLAY=:99 PYTHONPATH=. python3 data/scrape_anjuke.py \
  --login --manual --xvfb --region beijing_dongchenga \
  --profile chrome_profile_cube

# 步骤 2: 启动爬虫（使用 state 文件，不用 profile）
DISPLAY=:99 PYTHONPATH=. nohup python3 data/scrape_anjuke.py \
  --region beijing_tongzhou --shangquan all --xvfb \
  >> /tmp/cube_tongzhou.log 2>&1 &
```

**关键参数**:
- `--xvfb`: 非 headless（渲染到 Xvfb 虚拟显示器）+ 验证码快速跳过（不等待人工）
- `--profile DIR`: 仅用于登录阶段，利用持久化 profile 的会话信誉
- `DISPLAY=:99`: 指向 Xvfb 虚拟显示器

### 21. `--xvfb` 与 `--show` 的区别

| 参数 | headless | 验证码行为 | 适用场景 |
|------|----------|-----------|---------|
| (默认) | True | 快速跳过 | 不适合生产 |
| `--show` | False | 等 10 分钟人工 | 本地 Mac |
| `--xvfb` | False | 快速跳过 | CubeMini Xvfb |

### 22. 🐛 SQL LIKE 的 `_` 是通配符 — fill_shangquan 跨城误配根因 (2026-08-06 修复)

`fill_shangquan.py` 曾用 `community_id LIKE '%_{ajk_id}'` 匹配小区。**但 SQL LIKE 里 `_` 匹配任意单字符，不是字面下划线**。导致：

- 上海商圈页 ID `405678` 会误配成都小区 ID `1405678`（`_` 匹配 `1`，`405678` 匹配后缀）
- 只要 anjuke 社区数字 ID 有后缀重叠，就跨城市误配 → 3,097 条跨城垃圾商圈
- 加上无城市限定，污染范围扩大到全国

**修复**（`fill_shangquan.py`）:
```sql
WHERE shangquan_id IS NULL AND city_id = ?
  AND community_id LIKE ? ESCAPE '\'
-- 参数: (shangquan_id, city, f"%\_ {ajk_id}")  -- %\_ 是字面下划线
```

**校验**: `python3 validate_shangquan.py` — C1 检查跨城，爬完/填完必跑。

### 23. 🐛 district_id 中文/slug 混用 — 层级 join 断裂 (2026-08-06 修复)

`migrate_add_districts.py` 本意生成 slug 格式 district_id，但 chengdu/xa/datong 产出中文（`chengdu_武侯`），且 `name`/`slug` 列语义颠倒（name 存英文、slug 存中文）。导致 `communities.region_id`（slug）无法 join `districts.district_id`。

**修复**（`fix_district_id.py`）: district_id 统一为 `{city}_{url_slug}`（URL 末尾 slug），级联更新 shangquans.district_id + shangquan_id + communities.shangquan_id。爬虫生成 shangquan_id 也改为用 JSON 的 district `slug` 字段（`scrape_anjuke.py:891`）。

### 24. 本地 Mac 实际出网 IP 是 120.12.17.243 (河北栾城)，不是北京

抓 `sy-city.html` 时验证码页显示 `ws:120.12.17.243`，`ipinfo.io` 确认 IP=120.12.17.243（河北栾城，联通）。README 早期"本地 Mac 北京 IP"的假设是错的。这解释了批量重爬的验证码墙（IP 疲劳）和 `www.anjuke.com` 跳转 zhangjiakou。

`--xvfb` 解决了核心矛盾：需要非 headless 渲染（避免 headless 检测），但不能等人工过验证码（CubeMini 上没人）。

---

## 🛠️ 工具脚本速查

| 脚本 | 用途 | 用法 |
|------|------|------|
| `session_factory.py` | 🔑 创建 per-city 会话 | `python3 session_factory.py [--cities bj,sh]` |
| `data/scrape_anjuke.py` | 主爬虫 | `--region ID --shangquan all [--xvfb] [--profile DIR] [--state FILE]` |
| `launch_cube.py` | CubeMini 远程启动器 | `python3 launch_cube.py` |
| `sync_state_to_cubemini.py` | 同步状态 + CubeMini 状态查看 | `python3 sync_state_to_cubemini.py [--kill] [--restart C D] [--no-sync]` |
| `discover_shangquan.py` | 发现城市的所有商圈 → JSON | `python3 data/discover_shangquan.py {slug} {城市名}` |
| `fill_shangquan.py` | 为已有小区补商圈关联 | `python3 fill_shangquan.py` |
| `backup_db.sh` | 备份 DB → 本地 + CubeMini | `./backup_db.sh` |
| `migrate_add_districts.py` | 创建 districts/shangquans 表 | 已执行 |
| `gen_auto_regions.py` | 从商圈 JSON 生成 region config | `python3 gen_auto_regions.py` |
| `fix_district_type.py` | districts.type 回填(2026-09) | `python3 fix_district_type.py` |
| `resume_b4.sh` | B4 按商圈重爬·冷却续跑(崩溃自动恢复) | `nohup ./resume_b4.sh &` |
| `run_b1_details.sh` | B1 补详情·冷却续跑 | `nohup ./run_b1_details.sh &` |
| `data/scrape_anjuke.py --fix-names` | 空名称恢复(详情页提取, 只UPDATE name) | `--region X --fix-names --show` |

> 📌 `validate.py` 四维校验 + `adversarial_test.py` 对抗自检 — 任何脚本改动/新爬后必跑。

### 已弃用脚本 (仅供参考)

`cube_expand.py`, `cube_details.py`, `cube_crawler.py`, `cube_batch.py`, `batch_beijing.py`, `batch_runner.py`, `export_cubemini.py`, `dual_launcher.py` — 均被主爬虫 + session_factory 架构取代。

---

## 🎯 四阶段补全计划 (2026-07-31 ~ 2026-08-04，已完成)

### Phase 1: 详情修复 `--details-only`

**问题**: 844 条社区缺详情（因验证码阻断导致详情页未爬取）。

**方案**: 逐区运行 `--details-only --show`，利用可见 Chrome + 人工解验证码（`--show` 模式 100% 可靠）。

**结果**: 844 → 0 缺详情（17 个批次，累计 ~8 小时）。

```bash
PYTHONPATH=. python3 data/scrape_anjuke.py --region beijing_beijingzhoubiana --details-only --show
```

### Phase 2: 北京 6 新区全量爬取

**问题**: 北京 17 区仅覆盖 11 区，缺密云/平谷/门头沟/顺义/大兴/通州。

**方案**: 逐区 `--shangquan all --show` 全量爬取，利用断点续跑自动跳过已完成商圈。

**结果**: 新增 1,607 社区，北京 17/17 区全部 100% 覆盖。

### Phase 3: 商圈 ID 网页遍历回填

**问题**: 62.2% 社区缺 `shangquan_id`（28,495 条），因早期数据按区爬取，未关联商圈。

**方案**: 
1. `fill_shangquan.py` 逐商圈访问列表页，提取社区 Anjuke ID 精确匹配
2. 优化城市排序（低填充率城市优先）加速可见产出
3. SQL 地址/名称模糊匹配作为补充

**结果**: 37.8% → 74%（+17,000 条）。

### Phase 4: 区域众数批量填充

**问题**: Phase 3 后仍有 12,339 条社区缺商圈 ID——这些社区按区爬取，不出现在商圈列表页上。

**方案**: SQL 区域众数匹配——同一 `region_id` 内已有商圈 ID 的社区中取众数，分配给该区所有未填充社区。准确率取决于区域内商圈分布均匀度。

```sql
-- 每个区取最频繁的 shangquan_id，分配给所有 NULL
UPDATE communities SET shangquan_id = (
    SELECT shangquan_id FROM communities c2 
    WHERE c2.region_id = communities.region_id AND c2.shangquan_id IS NOT NULL 
    GROUP BY shangquan_id ORDER BY COUNT(*) DESC LIMIT 1
) WHERE shangquan_id IS NULL;
```

**结果**: 74% → 100%（+12,339 条）。全部 46,924 社区商圈 ID 填充完毕。

### 关键修复: scrape_anjuke.py 的 district 匹配 bug

**Bug**: `scrape_all_shangquan()` 中 `district_name` 参数来自 `region_id.split("_")[1]`（英文 slug，如 "wuhou"），而商圈 JSON 的 district key 是中文（如 "武侯"），永远无法匹配。导致 `--shangquan all` 对非 slug-key 城市返回 "0 shangquans"。

**修复**: 
1. 传入 `district_display_name = region.get("name", "")`（中文名）
2. 匹配逻辑扩展为四路匹配：slug / display_name / JSON key / info.name

```python
# data/scrape_anjuke.py line ~873
if district_name and dist_name != district_name \
    and dist_name != district_display_name \
    and dist_info_name != district_name \
    and dist_info_name != district_display_name:
    continue
```

### IP 风控规律补充

| 发现 | 详情 |
|------|------|
| `--show` 100% 可靠 | 整个 Phase 1 仅 3-4 次验证码，人工秒解 |
| IP 疲劳周期 | 连续 8.5h 后验证码频率从 1次/3h 升至 1次/5min |
| 冷却有效 | 30-60min 冷却后验证码频率大幅下降 |
| fill_shangquan 优势 | 2min captcha 超时 vs scraper 10min，更适合无人值守 |
| 双进程冲突 | 同一 IP 运行两个 Chrome 进程（fill + scrape）显著增加验证码 |

---

## 🎯 下一步

### 短期
- [ ] 对非北京城市执行按商圈重爬（成都 25 区、西安 8 区、上海 2 区等），替换 Phase 4 的区域众数填充为精确匹配
- [ ] 修复 `--listings-only` 与 `--shangquan all` 的组合支持（当前 `batch_shangquan` 路径未检查 `listings_only`）
- [ ] 北京朝阳/海淀商圈 ID 精细回填（当前 94%/96%——剩余为按区爬取数据，需按商圈重爬）

### 中长期
- [ ] FTS 全文搜索 + 空间索引
- [ ] LLM 探盘文案批量生成
- [ ] 扩展到其他城市（需先 discover_shangquan.py）

### 日常操作

```bash
# ═══ 检查 DB 状态 ═══
PYTHONPATH=. python3 -c "
from db.connection import get_db
conn = get_db()
total = conn.execute('SELECT COUNT(*) FROM communities').fetchone()[0]
detail = conn.execute('SELECT COUNT(*) FROM communities WHERE detail_scraped_at IS NOT NULL').fetchone()[0]
zero_c = conn.execute(\"SELECT COUNT(*) FROM communities WHERE (coordinate_lng=0 OR coordinate_lat=0)\").fetchone()[0]
null_sq = conn.execute('SELECT COUNT(*) FROM communities WHERE shangquan_id IS NULL').fetchone()[0]
print(f'总:{total:,} 详情:{detail:,}({detail/total*100:.0f}%) 零坐标:{zero_c} 缺商圈:{null_sq}')
conn.close()
"

# ═══ 修复缺详情 (人工解验证码) ═══
PYTHONPATH=. python3 data/scrape_anjuke.py --region XXX --details-only --show

# ═══ 爬取新区 ═══
PYTHONPATH=. nohup python3 data/scrape_anjuke.py \
  --region beijing_XXX --shangquan all --show >> /tmp/bj_XXX.log 2>&1 &

# ═══ 商圈 ID 回填 ═══
PYTHONPATH=. python3 fill_shangquan.py

# ═══ SQL 区域众数填充 (最后手段) ═══
PYTHONPATH=. python3 -c "
from db.connection import get_db; conn = get_db()
for r in conn.execute('SELECT DISTINCT region_id FROM communities WHERE shangquan_id IS NULL').fetchall():
    mode = conn.execute('SELECT shangquan_id, COUNT(*) c FROM communities WHERE region_id=? AND shangquan_id IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT 1', (r[0],)).fetchone()
    if mode: conn.execute('UPDATE communities SET shangquan_id=? WHERE region_id=? AND shangquan_id IS NULL', (mode[0], r[0]))
conn.commit(); conn.close()
print('Done')
"

# ═══ 运行中检查 ═══
tail -30 /tmp/bj_*.log                       # 本地进度
grep -c "Fields:" /tmp/bj_*.log               # 已完成详情数
grep "验证码\|captcha" /tmp/bj_*.log | wc -l  # 验证码次数
```

---

## ⚠️ 关键提醒

1. **按商圈爬，不要按区爬** — 大区会触发翻页上限
2. **IP 隔离是铁律** — 不能跨机器 sync session。每台机器必须在自己的 IP 上登录
3. **CubeMini 用 state 文件，不用 --profile 爬取** — 登录用 profile，爬取用 state 文件
4. **两个 IP 同时跑不同区** — 本地 Mac 跑一个北京区，CubeMini 跑另一个北京区
5. **改代码后重启进程** — Python 不热加载
6. **CubeMini 验证码恢复** — 重新运行登录脚本（持久化 profile 自动清除验证码）
7. **备份 DB 后再做任何迁移**
8. **headless 连续空结果 = 验证码墙** — 自动保存进度退出，不会死循环
9. **region_id 用 slug 不是中文名** — `beijing_xicheng` 的 district 部分是 `xicheng`，不是 `西城`
10. **断点续跑** — progress JSON 自动记录已完成商圈，重启跳过
11. **CubeMini 用 --xvfb 不用 --show** — xvfb 非 headless 但验证码快速跳过
12. **永远不要删除 Chrome profile** — 信誉是时间积累的
13. **同 session 登录+爬取** — 避免 kill/restart 触发风控
14. **本地 Mac --show 是 100% 可靠方案** — 验证码出现人工可解，不影响进度
15. **`--shangquan all` 的 district 匹配** — 需同时匹配 slug + 中文名（已修复，见 Phase 2 关键修复）
16. **`--details-only` 不修复零坐标** — 仅修复 `detail_scraped_at IS NULL` 的社区；零坐标但已有详情的社区需单独处理（访问详情页提取坐标）
17. **`--listings-only` 对 `--shangquan all` 无效** — batch_shangquan 代码路径未检查 listings_only 标志
18. **fill_shangquan vs 按商圈重爬** — fill_shangquan 只能匹配已出现在商圈列表页的社区；按区爬取的历史数据需要实际按商圈重爬才能精确匹配

---

## 📊 数据质量校验 (2026-08-04)

| 指标 | 值 | 状态 |
|------|-----|------|
| 重复 community_id | 0 | ✅ |
| 空名称 | 0 | ✅ |
| 零坐标 | 0 | ✅ |
| 缺失坐标 | 0 | ✅ |
| 详情覆盖率 | 46,924/46,924 (100%) | ✅ |
| 商圈ID覆盖率 | 46,924/46,924 (100%) | ✅ |
| 均价范围 | 400 ~ 297,989 元/㎡ | ✅ |
| 北京覆盖 | 17/17 区 (100%) | ✅ |

**全部指标清零达标。商圈 ID 的 12,339 条通过区域众数填充——精确度取决于各区商圈分布。后续按商圈重爬可替换为精确值。**

---

## 🔬 验证码风控规律

### 双机实测数据

| 机器 | 模式 | 完成率 | 验证码表现 |
|------|------|--------|-----------|
| 本地 Mac | --show (visible) | **100%** (6/6区) | 出现但人工可解 |
| CubeMini 旧profile | xvfb | **100%** (通州24商圈) | 自动清除 |
| CubeMini 新profile | xvfb+VNC | **60%** (大兴/顺义) | 每轮6-14商圈 |
| CubeMini 后期 | xvfb+VNC | **5%** (密云) | IP累计限流 |

### 核心规律

1. **Visible Chrome 无敌**: 安居客无法区分人工和爬虫操作同一个 Chrome
2. **Profile 信誉是时间函数**: 旧 profile 数周信誉=自动清验证码，删了归零
3. **IP 限流累积**: 每次失败尝试都增加风险评分，密集调试后 IP 严重限流
4. **kill/restart 加速封禁**: 同 session 内登录→爬取 远优于 登录→杀→重启→爬取

### 当前最优策略

```bash
# 主力: 本地 Mac --show (100% 可靠)
PYTHONPATH=. nohup python3 data/scrape_anjuke.py \
  --region beijing_XXX --shangquan all --show >> /tmp/bj_XXX.log 2>&1 &

# 辅助: CubeMini --xvfb --manual (同session，省掉kill步骤)
DISPLAY=:99 PYTHONPATH=. nohup python3 data/scrape_anjuke.py \
  --region beijing_XXX --shangquan all --xvfb --manual >> /tmp/cube_XXX.log 2>&1 &
```

---

## 📋 会话交接 (2026-09-07 · 最新)

> 完整决策/待办见 **TODO.md**, 全案评估见 **PROJECT_REVIEW.md**。本节为最新会话速记。

### 本次完成 (2026-09-01~07)
- **B4 按商圈重爬收官**: shenzhen/guangzhou/shanghai 全商圈遍历, 缺商圈 3,672 → 107(剩跨市盘/真孤儿诚实空值)
  - 分页死循环修复: `scrape_listing` 加"连续 12 页 0 新增即停"(东莞桶曾翻 92 页)
  - 健壮续跑: `resume_b4.sh`/`run_b1_details.sh`(崩溃 TargetClosedError 自动恢复 + 600s IP 冷却)
- **B1 新社区详情补**: B4 周边桶发现 ~4,090 新社区(东莞/佛山/嘉兴等跨市)全量补详情 → 剩雁荡大厦 1(8-30 起被验证码墙, 需人工过码)
- **G4**: districts.type 118 条回填(`fix_district_type.py`, 79市辖区/13县/13功能区/6县级市/6其他/1自治县)
- **B3**: 空名称 103 条修复(`scrape_anjuke.py --fix-names` 新模式, 详情页 h1/og:title 恢复名称, 只 UPDATE name 列零数据丢失)
- **Bug 修复**: 跨城商圈名称匹配(深圳"光明"匹配到北京顺义光明)→ 解析改城市限定; 清理 13 条跨城错配

### 数据快照 (2026-09-07)
125,525 小区 | 详情 100%(剩雁荡大厦) | 空名称 0 | BLOCK 0 | 商圈 1,708

### 运营要点(09 月新增教训)
1. **验证码墙 → 冷却而非硬闯**: resume 脚本每次爬虫退出 sleep 600s; 30-60min 冷却显著降验证码(实测 shanghai 尾段冷却后 275→301 全通)
2. **长跑必崩**: Playwright TargetClosedError 每 ~8h 一次 → 所有大爬必须走 resume/循环脚本
3. **跨市盘是 B4 副作用**: 周边桶净增 ~4,000 跨市社区(待加 is_cross_city 标记, 见 TODO ②-5)
4. **详情字段天花板**: interpretation 仅 ~44% 小区有源数据; property_basic 08-11 才进解析器, 历史 45K 欠账待回填(见 TODO ②-4)

---

## 📋 会话交接 (2026-08-06)

### 完成的工作（本会话）
- **省市层级建立**: provinces(34) + cities(673) 表，从安居客 `sy-city.html` 抓权威列表 + GB/T 2260 标准映射，100% 匹配
- **回填**: communities 加 city_id/province_id (100%)；districts 补 langfang 3 区 + 杨凌，全挂城市/省；config 省市交叉校验
- **Bug 1 修复**: 3,097 条跨城商圈垃圾全 NULL（根因: fill_shangquan 的 LIKE `_` 通配符跨城误配）；fill_shangquan 改城市限定 + 字面下划线
- **Bug 2 修复**: district_id 统一 slug 格式（`fix_district_id.py`），级联 shangquans + communities.shangquan_id；爬虫生成 shangquan_id 改用 JSON slug
- **预防**: `validate_shangquan.py` 完整性校验（跨城/孤儿/join），爬完必跑
- **IP 发现**: 本地实际出网 IP = 120.12.17.243 (河北栾城)，非北京

### 工具链状态

| 工具 | 状态 | 备注 |
|------|------|------|
| `data/scrape_anjuke.py` | ✅ | `--listings-only`+`--shangquan all` 已支持；shangquan_id 用 slug 生成 |
| `fill_shangquan.py` | ✅ | 城市限定 + 字面下划线（Bug 1 根因修复） |
| `build_province_city.py` | ✅ | 建省/市表 |
| `backfill_province_city.py` | ✅ | 回填省市列 + 补 districts |
| `fix_district_id.py` | ✅ | district_id 统一 slug（Bug 2 修复） |
| `validate.py` | ✅ | **数据契约校验器（四维×两级），爬完必跑** |
| `check_crawl.py` | ✅ | **部分失败检测（预期vs实际，抓datong类静默失败）** |
| `validate_shangquan.py` | ✅ | 兼容旧入口（调用 validate.py 精简版） |
| `adversarial_test.py` | ✅ | 对抗性检查（注入bug验证校验器能抓） |
| `fetch_city_list.py` | ✅ | 抓安居客权威省市列表（需人工过码一次） |
| `scrape_huxingtu.py` | ✅ | 独立户型爬取（huxingtu_json），断点续跑 |
| `migrate_option1.py` | ✅ | 选项1迁移：cities 定稿地级市，县级子域存 anjuke_county_map.json |
| `data/scrape_anjuke.py` | ✅ | 详情已支持 property_basic_json + community_interpretation_json |
| `data/shangquan_*.json` | ✅ | 7 城 1,708 商圈 |
| CubeMini | ❓ | DB 落后本地，待同步 |

### 待处理

> ⚠️ 本清单为 08-06 历史快照, 已大部分完成或被决策变更。**当前唯一权威待办见 [TODO.md](TODO.md)**。
> 要点: B4 商圈重爬✅(3,672→107) / B1 详情补✅ / 全量户型爬取 ❌永久移除 / 新房 ❌本轮不做。

### 快速验证命令
```bash
# ═══ 数据完整性（爬完必跑）═══
python3 validate.py                    # 四维契约校验 (结构/GB/爬取契约/业务)
python3 check_crawl.py                 # 部分失败检测 (预期 vs 实际, 抓静默漏爬)
python3 adversarial_test.py            # 对抗性自检 (注入bug验证校验器)

# ═══ 基础指标 ═══
PYTHONPATH=. python3 -c "
from db.connection import get_db; conn = get_db()
t = conn.execute('SELECT COUNT(*) FROM communities').fetchone()[0]
d = conn.execute('SELECT COUNT(*) FROM communities WHERE detail_scraped_at IS NOT NULL').fetchone()[0]
z = conn.execute(\"SELECT COUNT(*) FROM communities WHERE (coordinate_lng=0 OR coordinate_lat=0 OR coordinate_lng IS NULL)\").fetchone()[0]
s = conn.execute('SELECT COUNT(*) FROM communities WHERE shangquan_id IS NOT NULL').fetchone()[0]
p = conn.execute('SELECT COUNT(*) FROM communities WHERE province_id IS NOT NULL').fetchone()[0]
print(f'总:{t:,} 详情:{d:,}({d/t*100:.0f}%) 零坐标:{z} 商圈:{s:,}({s/t*100:.0f}%) 省:{p:,}')
conn.close()
"

# ═══ 修复 NULL 商圈（按商圈重爬回填）═══
PYTHONPATH=. python3 data/scrape_anjuke.py --region chengdu_XXX --shangquan all --listings-only
```
