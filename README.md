# Product Tracker 🔍

产品发现平台数据追踪器 —— 定期拉取 Product Hunt、Hacker News、BetaList、GitHub Trending 等平台数据，自动生成分析报告。

## 📋 功能特性

- **多平台采集**: Product Hunt、Hacker News (Show HN)、BetaList、GitHub Trending
- **稳定数据源优先**: 能用官方 feed / API 的平台就不抓 HTML，并保留 HTML 回退路径
- **跨平台去重**: 同一产品出现在多个榜单时自动合并，并记录它还出现在哪些平台
- **热度归一化**: 各平台热度量级不可比（GitHub 上万星 vs HN 几十票），统一折算为平台内百分位
- **赛道聚合**: 自动把产品归入 19 个赛道，趋势判断落在赛道层面而不是单个产品
- **决策信号**: 自动生成赛道升温/降温、跨平台共现、单品热度飙升、新品集中方向等结论并置顶
- **单品动量**: 记录每个产品相对上一次采集的票数/星数变化，区分持续升温与一次性曝光
- **趋势对比**: 与过去 N 天的数据对比，识别新品与关键词涨跌
- **精确关键词匹配**: 按词边界匹配（含复数形式），避免 `available` / `email` 被误判为 AI 相关
- **交互式看板**: HTML 报告可搜索、筛选、排序，单文件离线可用
- **多格式报告**: HTML（交互看板）、JSON（供程序消费）、Markdown（适合入库）
- **定时调度**: 支持固定间隔或 cron 表达式
- **自动清理**: 按保留天数清理过期数据与报告

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 执行一次数据采集

```bash
# 采集数据并生成默认格式报告
python main.py run

# 生成多种格式并在浏览器中打开
python main.py run --format html json markdown --open

# 只采集指定平台（忽略配置里的开关）
python main.py run --platform hackernews github_trending
```

### 3. 启动定时任务

```bash
# 按 config.yaml 的计划持续运行（默认启动时立即跑一次）
python main.py schedule

# 只执行一次后退出
python main.py schedule --once
```

Windows 用户也可以直接双击 `run.bat` 使用交互菜单。

## 🧩 支持的平台

| 平台 | 数据源 | 热度指标 | 状态 |
|------|--------|----------|------|
| Product Hunt | 官方 Atom feed，回退 hunted.space | 无（feed 不含票数） | ✅ |
| Hacker News | Algolia 搜索 API，回退官方 Firebase API | 得票数 / 评论数 | ✅ |
| BetaList | 站点 HTML | 无 | ✅ |
| GitHub Trending | 站点 HTML | 周期内新增星数 | ✅ |
| DevHunt | 站点 HTML | 排名 | ⚠️ 站点已下线，默认关闭 |

> Hacker News 用 Algolia API 而非官方 API：官方接口需为每条内容单独发一次请求（40 条约 40 次），
> Algolia 一次请求即可返回全部字段，且带票数与评论数。

## 📁 项目结构

```
product_tracker/
├── config.yaml          # 配置文件
├── main.py              # 主程序入口与 CLI
├── scheduler.py         # 定时调度器（含最小 cron 实现）
├── keywords.py          # 关键词匹配（词边界 + 复数，避免误报）
├── platforms.py         # 平台展示名与热度口径
├── requirements.txt     # 依赖列表
├── run.bat              # Windows 交互菜单
├── collectors/          # 数据收集器
│   ├── base.py             # 基类：会话复用、重试退避、限流、代理
│   ├── producthunt.py
│   ├── hackernews.py
│   ├── betalist.py
│   ├── devhunt.py
│   └── github_trending.py
├── analyzers/           # 分析与报告
│   ├── analyzer.py         # 热度归一化、赛道动量、决策信号、历史对比
│   ├── themes.py           # 赛道分类体系（按标题/标签/正文加权匹配）
│   └── report_generator.py # 交互看板 HTML / JSON / Markdown 报告
├── tests/               # 离线单元测试
├── data/                # 原始采集数据（JSON）
├── reports/             # 生成的报告
└── logs/                # 滚动日志
```

## 📝 命令行参数

```
usage: main.py [-h] [--config CONFIG] [--format {html,json,markdown} ...]
               [--platform NAME ...] [--once] [--open] [--verbose] [--version]
               {clean,config,report,run,schedule,status}

命令:
  run       采集数据、分析并生成报告
  schedule  按 config.yaml 的计划持续运行
  report    用最近一次已采集的数据重新生成报告（不联网）
  config    打印当前生效配置
  status    显示平台开关、调度设置与历史产物
  clean     按 retention_days 清理过期数据与报告

选项:
  -c, --config CONFIG      配置文件路径
  -f, --format FORMAT      报告格式，可多选 (html/json/markdown)
  -p, --platform NAME      只采集指定平台，忽略 enabled 开关
      --once               schedule 命令下只执行一次
      --open               生成后在浏览器中打开 HTML 报告
  -v, --verbose            输出调试日志
      --version            显示版本
```

## ⚙️ 配置说明

完整可用配置见 `config.yaml`，以下是常用项。

### 平台开关与采集量

```yaml
platforms:
  hackernews:
    enabled: true
    rate_limit: 1      # 同平台两次请求的最小间隔（秒）
    timeout: 30        # 单次请求超时
    max_retries: 3     # 失败重试次数（指数退避）
    max_items: 40      # 最多保留条目
    window_days: 7     # 只取最近 7 天的 Show HN
```

### 调度方式

```yaml
scheduler:
  enabled: true
  run_on_start: true       # 启动后立即跑一次
  use_cron: false          # true 时用 cron_expression，否则用 interval_minutes
  cron_expression: "0 9 * * *"
  interval_minutes: 1440
```

cron 支持标准 5 字段与 `*`、`*/n`、`a-b`、`a,b,c`（周日为 `0`）。表达式非法时会记录错误并自动退回间隔模式。

### 分析与保留

```yaml
analysis:
  trend_window_days: 7     # 与过去几天对比
  keywords: ["AI", "agent", "SaaS"]   # 需要跟踪的关键词
  report_formats: ["html", "json", "markdown"]
  retention_days: 90       # 数据与报告保留天数
```

### 代理与日志

```yaml
proxy:
  enabled: true
  http: "http://127.0.0.1:7890"
  https: "http://127.0.0.1:7890"

logging:
  level: "INFO"
  file: "./logs/tracker.log"
  max_size_mb: 10
  backup_count: 5
```

## 📊 报告内容

HTML 报告是一个交互看板，按「结论 → 趋势 → 明细」组织，让人先看到变化再下钻：

1. **本次结论** —— 自动生成的决策信号卡，按重要性排序。包括赛道升温/降温（附环比百分点）、
   跨平台同时出现的产品、热度加速上涨的单品（附涨幅）、直接冲进平台前列的新品、
   新品最集中的赛道。点击卡片可筛选下方明细。
2. **赛道热力** —— 19 个赛道的数量、占比、与过去 N 天的环比变化、新品数。点击任一行筛选明细。
3. **产品明细** —— 全部产品的紧凑表格，支持搜索、按平台/赛道/新品/高热度/上涨中筛选、
   按各列排序（含「较上次」动量列），点击行展开完整描述与在榜信息。
4. **附录** —— 热度口径说明、高频词、关键词环比、标签分布。

快捷键：`/` 聚焦搜索、`n` 只看新品、`Esc` 清除所有筛选。

报告是单个自包含 HTML 文件（内联 CSS/JS 与数据），无外部依赖，可离线打开或直接分发。

### 关于热度分

各平台的热度量级完全不可比 —— GitHub Trending 是上万星，Hacker News 是几十票，
Product Hunt feed 和 BetaList 根本不提供公开票数。直接同榜排序会让 GitHub 垄断榜首。

因此表中的**热度分**是该产品在**所属平台内**的百分位（0-100），跨平台可比；
**原始值**列保留各平台自己的口径。没有公开热度数据的平台按列表顺序折算，热度条显示为灰色，
提醒这不是真实热度。各平台的具体口径在报告附录中列出。

### 关于「较上次」

**较上次**是该产品相对上一次采集的票数/星数变化，回答「它还在涨吗」。只有提供真实票数的平台
（Hacker News、GitHub Trending）才有这一列；Product Hunt feed 与 BetaList 的热度来自榜单位次，
位次波动不代表热度变化，因此显示为 `—` 而不是编造一个数字。首次出现的产品同样显示 `—`。

「热度加速上涨」信号按**相对涨幅**排序而非绝对增量 —— 两万星涨 500 是正常增速，
20 票涨到 80 才说明问题。信号要求增量至少 10 且涨幅超过 20%，以过滤掉小基数噪声。

## 🧪 运行测试

```bash
pip install pytest
python -m pytest tests -q
```

测试全部离线运行，用固定的 HTML / Atom / JSON 片段验证解析、去重、cron 与报告生成。

## 🔧 扩展新平台

1. 在 `collectors/` 下新建收集器，继承 `BaseCollector`，实现 `collect()` 与 `_parse_product()`：

```python
from .base import BaseCollector, CollectorError, Product

class MyPlatformCollector(BaseCollector):
    def collect(self) -> List[Product]:
        data = self._make_json_request(f"{self.base_url}/api/items")
        if data is None:
            raise CollectorError("数据源不可用")
        return self._dedupe([self._parse_product(x) for x in data])[:self.max_items]

    def _parse_product(self, data: Dict) -> Optional[Product]:
        return Product(id=..., name=..., description=..., url=..., platform="myplatform")
```

基类已提供限流、重试退避、代理与 `_make_request` / `_make_json_request` / `_make_xml_request`。

2. 在 `collectors/__init__.py` 的 `COLLECTORS` 中注册。
3. 在 `platforms.py` 加展示名，在 `config.yaml` 加配置段。

## 🛠️ 故障排除

**采集不到数据**: 用 `python main.py run -v` 看调试日志。HTML 类数据源（BetaList、GitHub Trending）依赖页面结构，站点改版后需要更新选择器。

**中文/emoji 显示乱码**: 程序已将输出重定向为 UTF-8；若在 `cmd.exe` 中仍有问题，先执行 `chcp 65001`（`run.bat` 已内置）。

**需要走代理**: 在 `config.yaml` 的 `proxy` 段开启，对所有平台生效。

**日志在哪**: `logs/tracker.log`，按 10MB 滚动保留 5 份。

## 📄 许可

MIT License
