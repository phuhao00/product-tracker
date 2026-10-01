# Product Tracker

从 Product Hunt、Fazier、DevHunt、Indie Hackers、Hacker News、新趣集 等 13 个产品发现平台定期采集数据，归入赛道、算热度与动量，生成**可直接用来做判断**的交互看板。

目标不是堆数据，而是回答三件事：

1. **现在该看哪几个产品？**（今日关注）
2. **哪个赛道在升温 / 降温？**（赛道热力 + 结论卡）
3. **某个产品还在涨吗？**（较上次）

## 功能

- **多平台采集**：打榜类（Product Hunt、Fazier、StartuPage、Uneed、MicroLaunch、Peerlist）、早期内测类（BetaList、Betabound）、开发者类（Hacker News、DevHunt、GitHub Trending）、创作者社区与国内（Indie Hackers、新趣集）
- **优先取结构化数据**：能用官方 feed / API / 站点内联 JSON 就不抓 HTML，并保留 HTML 回退
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

按用途分四组，与 `platforms.PLATFORM_GROUPS` 一一对应。

### 一、打榜与每日精选（最接近 Product Hunt）

| 平台 | 数据源 | 热度指标 | 状态 |
|------|--------|----------|------|
| Product Hunt | 官方 Atom feed + embed 徽章补票数；回退 hunted.space | 得票数 | ✅ |
| Fazier | 首页 `__NEXT_DATA__` 内联 JSON；回退 HTML 卡片 | 得票数 | ✅ |
| StartuPage | `/leaderboard?tab=startups` 榜单行 | Stripe 验证 MRR | ✅ |
| Uneed | 站点 HTML | 列表顺序 | ⚠️ Cloudflare 整站 403，默认关闭 |
| MicroLaunch | 站点 HTML | 列表顺序 | ⚠️ Cloudflare 整站 403，默认关闭 |
| Peerlist Launchpad | 无（纯客户端渲染） | 榜单排名 | ⚠️ 需无头浏览器，默认关闭 |

### 二、早期与内测阶段（找种子用户）

| 平台 | 数据源 | 热度指标 | 状态 |
|------|--------|----------|------|
| BetaList | 站点 HTML（另有 feedburner 订阅源） | 无 | ✅ |
| Betabound | 官方 RSS | 无 | ✅ |

### 三、开发者与技术社区

| 平台 | 数据源 | 热度指标 | 状态 |
|------|--------|----------|------|
| Hacker News | Algolia 搜索 API，回退 Firebase API | 得票数 / 评论数 | ✅ |
| DevHunt | Next.js flight 内联 JSON；回退 HTML 卡片 | 得票数 / 浏览量 | ✅ |
| GitHub Trending | 站点 HTML | 周期内新增星数 | ✅ |

### 四、创作者社区与国内平台

| 平台 | 数据源 | 热度指标 | 状态 |
|------|--------|----------|------|
| Indie Hackers | 站点 HTML（BEM 类名） | Stripe 验证 MRR | ✅ |
| 新趣集 | 官方 RSS | 无 | ✅ |

> - Hacker News 优先用 Algolia：官方接口需逐条请求，Algolia 一次返回票数与评论数。
> - Fazier 与 DevHunt 都采用 Next.js，把整份榜单数据内联在页面里。直接解析这份 JSON
>   比抓 HTML 稳定，而且能拿到票数、分类与定价 —— 这是 2025 年后这两个站点的共同特点。
> - DevHunt 在 2025 年改版后已恢复可用，旧版本全站返回 Next.js 错误页，本项目据此
>   曾默认关闭它，现已重新启用。

## 项目结构

```
product_tracker/
├── config.yaml          # 配置
├── main.py              # CLI 入口（采集、历史窗口、去重）
├── scheduler.py         # 定时调度（含最小 cron）
├── keywords.py          # 词边界匹配（复数、camelCase）
├── platforms.py         # 平台展示名、分组与热度口径
├── collectors/          # 各平台采集器
│   ├── base.py             # 基类：限流、重试退避、代理
│   ├── rss.py              # RSS / Atom 统一解析（新趣集、Betabound 共用）
│   ├── blocked.py          # 被 Cloudflare 拦截平台的公共基类（Uneed、MicroLaunch）
│   └── <platform>.py       # 每个平台一个采集器
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
3. 在 `platforms.py` 加展示名、分组与热度口径，在 `config.yaml` 加配置段
4. 补一条离线解析单测（用内联样本驱动，不联网）

基类已提供限流、重试退避、代理与 `_make_request` / `_make_json_request` / `_make_xml_request`。

按数据源类型可以直接复用现成实现，不必从零写：

| 数据源形态 | 参考实现 |
|------------|----------|
| 官方 RSS / Atom | 继承基础上用 `collectors/rss.py` 的 `parse_feed()`，见 `xinquji.py`、`betabound.py` |
| Next.js 内联 JSON（`__NEXT_DATA__`） | `fazier.py` |
| Next.js flight 负载（RSC 分片推送） | `devhunt.py`，含括号配对切分嵌套对象的 `_iter_flight_objects()` |
| 站点 HTML | `betalist.py`（BEM 或工具类选择器）、`indiehackers.py` |
| 整站被 WAF 拦截 | 继承 `collectors/blocked.py` 的 `WafBlockedCollector`，见 `uneed.py` |

> **优先选结构化数据源**：站点用 Next.js 时，先找 `__NEXT_DATA__` 或 `self.__next_f.push`，
> 里面的字段通常比 DOM 齐全（含票数、分类、定价），也不受样式类名改版影响。

## 故障排除

| 问题 | 处理 |
|------|------|
| 采集不到数据 | `python main.py run -v` 看日志；HTML 源站点改版需更新选择器 |
| 控制台乱码 | `chcp 65001`（`run.bat` 已内置） |
| 需要代理 | 打开 `config.yaml` 的 `proxy` |
| 日志位置 | `logs/tracker.log`（按大小滚动） |

## 已知限制

**票数缺口**：BetaList、Betabound 与新趣集不提供公开票数，因此没有「较上次」动量，热度分按榜单位次估算（灰色条）。Product Hunt 的 Atom feed 本身不含票数，本项目通过官方 `featured.svg` 徽章补齐；若徽章接口异常会自动跳过，退回按 feed 顺序估算。

**营收当热度**：Indie Hackers 与 StartuPage 不公开票数，改用 Stripe 验证的月收入（MRR）作热度口径。它衡量「有没有人付钱」，与「今天有多热」不是一回事，读这两行的数据时请按收入理解。另外 Indie Hackers 首页默认只展示 18 条，其中多数产品 MRR 为 $0，只有少数有真实收入。

**受限平台**（默认关闭，见 `config.yaml`）：

| 平台 | 原因 | 启用方式 |
|------|------|----------|
| Uneed | 整站由 Cloudflare 保护，对 requests/curl 恒返回 403，无公开 API | 在 `proxy` 段配置稳定出口的代理后置 `enabled: true` |
| MicroLaunch | 同上 | 同上 |
| Peerlist Launchpad | 纯客户端渲染，HTML 内不含榜单数据，公开 API 全部 404 | 需改用无头浏览器采集，非本项目的 HTTP 方式 |

三个受限平台的采集器都不会静默返回空结果，而是抛出带原因与处置建议的 `CollectorError`，日志里能看到明确提示。Uneed 与 MicroLaunch 的解析规则因站点无法访问而**尚未用真实页面验证**，首次启用请用 `python main.py run -p uneed -v` 核对解析结果。

## 许可

MIT License
