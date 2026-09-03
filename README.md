# Product Tracker

从 Product Hunt、Hacker News、BetaList、GitHub Trending 定期采集产品数据，归入赛道、算热度与动量，生成**可直接用来做判断**的交互看板。

目标不是堆数据，而是回答三件事：

1. **现在该看哪几个产品？**（今日关注）
2. **哪个赛道在升温 / 降温？**（赛道热力 + 结论卡）
3. **某个产品还在涨吗？**（较上次）

## 功能

- **多平台采集**：Product Hunt、Hacker News (Show HN)、BetaList、GitHub Trending
- **稳定数据源优先**：能用官方 feed / API 就不抓 HTML，并保留 HTML 回退
- **跨平台去重**：同一产品出现在多个榜单时合并，并记录它还出现在哪些平台
- **赛道聚合**：按标题 / 标签 / 正文加权归入约 19 个赛道（「其他」为兜底，不产生趋势信号）
- **热度归一化**：平台内百分位（0–100），跨平台可比；无公开票数的平台用榜单位次估算并灰色标注
- **单品动量**：相对上一次采集的票数 / 星数变化，区分持续升温与一次性曝光
- **决策信号**：今日关注短名单、赛道升温降温、跨平台共现、热度飙升、高位新品
- **交互看板**：单文件 HTML，可搜索 / 筛选 / 排序 / 展开，离线可用
- **多格式报告**：HTML、JSON、Markdown
- **定时调度**：固定间隔或 cron；按保留天数自动清理

## 快速开始

```bash
pip install -r requirements.txt

# 采集并生成报告
python main.py run

# 多格式 + 打开浏览器
python main.py run --format html json markdown --open

# 按 config.yaml 定时跑（默认启动时先跑一次）
python main.py schedule
```

Windows 也可双击 `run.bat` 使用交互菜单。更细的操作说明见 [USAGE.md](USAGE.md)。

只用已有数据重出报告（不联网）：

```bash
python main.py report --format html
```

## 报告怎么读

HTML 报告按 **结论 → 趋势 → 明细** 组织：

| 板块 | 用途 |
|------|------|
| **今日关注** | 综合热度、新品、跨平台、上涨动量挑出的短名单，优先点开这些 |
| **赛道结论** | 升温 / 降温（环比百分点）、飙升单品、冲进榜单前列的新品 |
| **赛道热力** | 各赛道数量、占比、去重后的环比、新品数；点击行可筛选明细 |
| **产品明细** | 搜索、平台 / 赛道 / 新品 / 高热度 / 上涨中筛选；「较上次」可排序 |
| **附录** | 各平台热度口径、高频词、关键词环比、标签分布 |

快捷键：`/` 聚焦搜索 · `n` 只看新品 · `Esc` 清除筛选。点击行可展开描述与在榜信息。

报告是单个自包含 HTML（内联 CSS / JS / 数据），无外部依赖，可直接发给别人。

### 热度分 vs 原始值 vs 较上次

| 列 | 含义 |
|----|------|
| **热度分** | 所属平台内百分位（0–100），跨平台排序用这个 |
| **原始值** | 各平台自己的口径（票数 / 星数）；无公开数据时为 `—` |
| **较上次** | 相对上一次采集的票数变化。HN / GitHub / Product Hunt 有值；BetaList 为 `—`（无公开票数） |

「热度加速上涨」按**相对涨幅**排序（增量 ≥ 10 且涨幅 > 20%），过滤小基数噪声。

赛道环比会先对历史窗口内同一产品去重，避免多次采集把分母冲大。

## 支持的平台

| 平台 | 数据源 | 热度指标 | 状态 |
|------|--------|----------|------|
| Product Hunt | 官方 Atom feed + embed 徽章补票数；回退 hunted.space | 得票数 | ✅ |
| Hacker News | Algolia 搜索 API，回退 Firebase API | 得票数 / 评论数 | ✅ |
| BetaList | 站点 HTML | 无 | ✅ |
| GitHub Trending | 站点 HTML | 周期内新增星数 | ✅ |
| DevHunt | 站点 HTML | 排名 | ⚠️ 站点已下线，默认关闭 |

> Hacker News 优先用 Algolia：官方接口需逐条请求，Algolia 一次返回票数与评论数。

## 项目结构

```
product_tracker/
├── config.yaml          # 配置
├── main.py              # CLI 入口（采集、历史窗口、去重）
├── scheduler.py         # 定时调度（含最小 cron）
├── keywords.py          # 词边界匹配（复数、camelCase）
├── platforms.py         # 平台展示名与热度口径
├── collectors/          # 各平台采集器
├── analyzers/
│   ├── analyzer.py         # 热度、赛道动量、今日关注、决策信号
│   ├── themes.py           # 赛道词表与加权分类
│   └── report_generator.py # HTML / JSON / Markdown
├── tests/               # 离线单元测试
├── data/                # 原始采集（gitignore）
├── reports/             # 生成的报告（gitignore）
└── logs/
```

## 命令行

```
python main.py {run|schedule|report|config|status|clean} [选项]

  run       采集 → 分析 → 出报告
  schedule  按配置持续跑
  report    用最近一次数据重出报告（不联网）
  config    打印生效配置
  status    平台开关、调度与历史产物
  clean     按 retention_days 清理

  -f/--format html json markdown
  -p/--platform hackernews github_trending
  --open    打开 HTML 报告
  -v        调试日志
```

## 配置要点

完整项见 `config.yaml`。常用片段：

```yaml
platforms:
  hackernews:
    enabled: true
    max_items: 40
    window_days: 7

scheduler:
  enabled: true
  run_on_start: true
  use_cron: false
  interval_minutes: 1440          # 或 cron: "0 9 * * *"

analysis:
  trend_window_days: 7
  keywords: ["AI", "agent", "SaaS"]
  report_formats: ["html", "json", "markdown"]
  retention_days: 90

proxy:
  enabled: false
  http: "http://127.0.0.1:7890"
  https: "http://127.0.0.1:7890"
```

## 测试

```bash
pip install pytest
python -m pytest tests -q
```

全部离线运行，覆盖解析、去重、关键词、赛道分类、热度归一化、历史窗口、单品动量与决策信号。

## 扩展新平台

1. 在 `collectors/` 继承 `BaseCollector`，实现 `collect()` / `_parse_product()`
2. 在 `collectors/__init__.py` 的 `COLLECTORS` 注册
3. 在 `platforms.py` 加展示名，在 `config.yaml` 加配置段

基类已提供限流、重试退避、代理与 `_make_request` / `_make_json_request` / `_make_xml_request`。

## 故障排除

| 问题 | 处理 |
|------|------|
| 采集不到数据 | `python main.py run -v` 看日志；HTML 源站点改版需更新选择器 |
| 控制台乱码 | `chcp 65001`（`run.bat` 已内置） |
| 需要代理 | 打开 `config.yaml` 的 `proxy` |
| 日志位置 | `logs/tracker.log`（按大小滚动） |

**已知限制**：BetaList 不提供公开票数，因此没有「较上次」动量，热度分按榜单位次估算（灰色条）。Product Hunt 的 Atom feed 本身不含票数，本项目通过官方 `featured.svg` 徽章补齐；若徽章接口异常会自动跳过，退回按 feed 顺序估算。

## 许可

MIT License
