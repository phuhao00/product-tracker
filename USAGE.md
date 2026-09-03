# Product Tracker 使用指南

面向日常使用的操作手册。项目总览与配置参考见 [README.md](README.md)。

## 🎯 快速开始

### 方法一：批处理菜单（Windows 推荐）

双击 `run.bat`，按提示选择操作。脚本已切换到 UTF-8 代码页，中文与 emoji 不会乱码。

### 方法二：命令行

```bash
cd "C:\Users\Administrator\Documents\Default Project\product_tracker"

# 安装依赖（首次）
pip install -r requirements.txt

# 采集一次并生成报告
python main.py run

# 生成三种格式并打开 HTML
python main.py run --format html json markdown --open

# 查看状态
python main.py status
```

一次完整采集（4 个平台，约 150 条）耗时 10 秒左右，主要花在各平台的限流等待上。

## 📅 日常使用场景

### 每天看一次新品

```bash
python main.py run --open
```

第二次及以后运行时，报告会多出「本次新发现」板块和关键词涨跌对比。

### 只关心开发者工具

```bash
python main.py run --platform hackernews github_trending --open
```

`--platform` 会忽略 `config.yaml` 里的 `enabled` 开关，适合临时查询。

### 报告写坏了想重新生成

```bash
python main.py report --format html markdown --open
```

`report` 命令使用最近一次已保存的原始数据，不会重新联网，适合调整报告样式后快速预览。

### 持续后台运行

```bash
python main.py schedule
```

按 `Ctrl+C` 停止。默认启动时立即执行一次，之后每 24 小时一次。

## ⚙️ 常用配置调整

编辑 `config.yaml` 后无需重启即可对下一次运行生效（`schedule` 常驻进程除外）。

### 改采集频率

```yaml
scheduler:
  interval_minutes: 720    # 12 小时
```

### 改成固定时间点执行

```yaml
scheduler:
  use_cron: true
  cron_expression: "0 9 * * *"      # 每天 09:00
  # "0 9,18 * * *"   每天 09:00 和 18:00
  # "*/30 * * * *"   每 30 分钟
  # "0 9 * * 1-5"    工作日 09:00
```

周日为 `0`。表达式写错时程序会记录错误并退回 `interval_minutes`，不会启动失败。

### 启用或关闭平台

```yaml
platforms:
  betalist:
    enabled: false
```

### 调整采集数量

```yaml
platforms:
  hackernews:
    max_items: 60
    window_days: 14      # 放宽到最近 14 天，能捞到票数更高的内容
```

### 跟踪自己关心的关键词

```yaml
analysis:
  keywords:
    - "AI"
    - "RAG"
    - "no-code"
```

这些词会出现在报告的「趋势分析」中，并参与与历史窗口的涨跌对比。报告里的「自动提取的高频词」不受此配置影响，它直接从当次数据统计。

### 走代理

```yaml
proxy:
  enabled: true
  http: "http://127.0.0.1:7890"
  https: "http://127.0.0.1:7890"
```

## 📈 报告怎么读

看板按「结论 → 趋势 → 明细」排列，不需要从头滚到尾。

| 板块 | 说明 |
|------|------|
| 顶栏 | 总量、平台数、赛道数，有历史时显示新发现数与热度上涨数 |
| 本次结论 | 自动生成的决策信号，按重要性排序。点击卡片可筛选下方明细 |
| 赛道热力 | 各赛道数量、占比、环比变化、新品数。点击行筛选明细 |
| 产品明细 | 全部产品，可搜索 / 筛选 / 排序 / 展开 |
| 附录 | 热度口径、高频词、关键词环比、标签分布 |

### 三步做判断

1. **看结论**：先看「今日关注」短名单（现在就该点开的产品），再看赛道升温/降温卡片。
2. **看赛道**：想知道整体格局就扫一眼赛道热力，`▲`/`▼` 是与过去 N 天去重后占比差（百分点）。
   注意「其他」是分类兜底桶，它的涨跌只反映分类覆盖度，因此不会产生任何信号。
3. **下钻明细**：点击某个赛道，明细表立刻只剩该赛道的产品；再按热度分排序就是该赛道的头部。

常用操作：`/` 聚焦搜索、`n` 只看新品、`Esc` 清除全部筛选；点击表头排序，点击行展开完整描述
与在榜信息（此前出现过几次、最早见于哪天）。「跨平台」筛选能挑出同时上了多个榜的产品，
这类信号通常比单平台高票更可靠；「上涨中」筛选只留下相对上次采集票数在涨的产品。

### 关于「热度分」与「原始值」

各平台热度量级差了三个数量级 —— GitHub Trending 上万星、Hacker News 几十票，
Product Hunt 与 BetaList 的 Atom/HTML 源本身不含票数；本项目会用官方 embed 徽章
为 Product Hunt 补票数。BetaList 仍无公开票数。放同一张榜直接比原始值，结果只会是 GitHub 霸榜。

所以看板里有两列：

- **热度分**：该产品在**所属平台内**的百分位（0-100），跨平台可比，用它排序才有意义。
- **原始值**：各平台自己的口径（票数 / 星数），无公开数据时显示 `—`。
- **较上次**：相对上一次采集的票数变化，回答「它还在涨吗」。

没有真实热度数据的平台，热度分由列表顺序折算，热度条显示为**灰色**，提醒这只是弱信号。
每个平台的具体口径写在报告附录的「热度口径说明」里。

「较上次」在 Hacker News、GitHub Trending、Product Hunt（经徽章补齐）上有值。
BetaList 仍无公开票数，热度按榜单位次估算（灰色条），「较上次」显示 `—`；
首次出现的产品同样显示 `—`。按这一列排序时，无数据的行始终排在最后。

热度分高只说明「现在热」，「较上次」才说明「还在涨」。两者结合看：热度分高但动量为 0 的多是
已经见顶的老面孔，热度分中等但持续上涨的往往更值得跟。

### 三种格式的用途

- **HTML**: 交互看板，单文件自包含（内联样式、脚本与数据），离线可开、可直接发给别人
- **JSON**: 结构化数据，字段与 `AnalysisResult` 一致，含 `signals` / `themes` / `products`，便于二次处理
- **Markdown**: 纯文本，同样是结论先行，适合提交到仓库或贴进文档

## 🔄 系统级定时任务

除了内置调度器，也可以交给操作系统。

### Windows 任务计划程序

1. 打开「任务计划程序」→ 创建基本任务
2. 触发器：每天
3. 操作：启动程序
   - 程序：`python`
   - 参数：`main.py run`
   - 起始目录：`C:\Users\Administrator\Documents\Default Project\product_tracker`

起始目录必须填写，否则日志与数据会写到别处（程序内部路径按项目根解析，但 `python main.py` 需要能找到脚本）。

### cron（WSL / Linux / macOS）

```bash
0 9 * * * cd /path/to/product_tracker && python main.py run >> logs/cron.log 2>&1
```

## 🛠️ 故障排除

### 采集数量异常偏少

```bash
python main.py run -v
```

调试日志会打印每个请求与解析结果。BetaList 与 GitHub Trending 依赖页面结构，站点改版后需要更新对应收集器的选择器；Product Hunt 与 Hacker News 走 feed/API，通常更稳定。

### 某个平台整体失败

日志会明确写出原因，例如：

```
ERROR - devhunt unavailable: devhunt.org is unavailable (all pages return an error page).
```

单个平台失败不会中断整次运行，其余平台照常采集。

### 请求超时或被限流

调大间隔与重试：

```yaml
platforms:
  github_trending:
    rate_limit: 5
    timeout: 60
    max_retries: 5
```

基类已对 429 与 5xx 做指数退避重试。

### 依赖缺失

```bash
pip install -r requirements.txt
```

### 查看日志

```powershell
Get-Content logs\tracker.log -Tail 50 -Wait
```

```bash
tail -f logs/tracker.log
```

### 磁盘占用变大

```bash
python main.py clean
```

按 `analysis.retention_days`（默认 90 天）清理过期数据与报告；每次 `run` 结束也会自动执行一次。

## 🧪 改代码后自测

```bash
python -m pytest tests -q
```

110 个离线测试，覆盖各平台解析、跨平台去重、关键词匹配、赛道分类、热度归一化、历史窗口、
单品动量、决策信号、cron 与报告生成，不需要联网。
