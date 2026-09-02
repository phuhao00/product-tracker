"""
报告生成器

HTML 报告是一个决策看板，遵循"结论 → 趋势 → 明细"的顺序：
先给出本次的变化信号，再展示赛道动量，最后才是可搜索筛选的产品明细。
"""

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Dict, List

from platforms import platform_label

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = ('html', 'json', 'markdown')

DIRECTION_ICONS = {'up': '▲', 'down': '▼', 'flat': '■'}

CSS = """
:root {
  --bg: #f6f7f9;
  --surface: #fff;
  --surface-2: #fafbfc;
  --text: #12161c;
  --muted: #6b7480;
  --border: #e3e6ea;
  --accent: #ff6154;
  --up: #17864a;
  --up-bg: #eaf6ee;
  --down: #c02b2b;
  --down-bg: #fdeeee;
  --flat: #6b7480;
  --radius: 10px;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 1240px; margin: 0 auto; padding: 0 20px 80px; }
a { color: inherit; }

/* ---------- 顶栏 ---------- */
.topbar {
  position: sticky; top: 0; z-index: 20;
  background: rgba(255,255,255,.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
}
.topbar-inner {
  max-width: 1240px; margin: 0 auto; padding: 12px 20px;
  display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
}
.brand { font-size: 15px; font-weight: 700; white-space: nowrap; }
.brand span { color: var(--muted); font-weight: 400; margin-left: 8px; font-size: 13px; }
.kpis { display: flex; gap: 22px; margin-left: auto; }
.kpi { text-align: right; }
.kpi b { display: block; font-size: 17px; line-height: 1.2; font-variant-numeric: tabular-nums; }
.kpi small { color: var(--muted); font-size: 11px; }
.kpi.hl b { color: var(--accent); }

/* ---------- 区块 ---------- */
section { margin-top: 36px; }
.sec-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }
.sec-head h2 { margin: 0; font-size: 16px; letter-spacing: .01em; }
.sec-head p { margin: 0; color: var(--muted); font-size: 12.5px; }

/* ---------- 信号卡 ---------- */
.signals { display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); gap: 14px; }
.signal {
  background: var(--surface); border: 1px solid var(--border);
  border-left: 3px solid var(--flat); border-radius: var(--radius);
  padding: 14px 16px; cursor: default;
}
.signal.up { border-left-color: var(--up); }
.signal.down { border-left-color: var(--down); }
.signal.clickable { cursor: pointer; }
.signal.clickable:hover { border-color: var(--accent); }
.signal-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.signal-top h3 { margin: 0; font-size: 14.5px; flex: 1; }
.dir { font-size: 11px; }
.dir.up { color: var(--up); }
.dir.down { color: var(--down); }
.dir.flat { color: var(--flat); }
.metric {
  font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
  font-variant-numeric: tabular-nums; white-space: nowrap;
  background: #eef0f3; color: var(--text);
}
.signal.up .metric { background: var(--up-bg); color: var(--up); }
.signal.down .metric { background: var(--down-bg); color: var(--down); }
.signal p { margin: 0 0 10px; color: var(--muted); font-size: 12.5px; }
.evidence { list-style: none; margin: 0; padding: 0; border-top: 1px dashed var(--border); padding-top: 8px; }
.evidence li { font-size: 12.5px; margin-top: 4px; display: flex; gap: 6px; }
.evidence a { font-weight: 600; text-decoration: none; }
.evidence a:hover { color: var(--accent); }
.evidence em { color: var(--muted); font-style: normal; font-size: 11.5px; white-space: nowrap; }

/* ---------- 赛道热力 ---------- */
.themes { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.theme-row {
  display: grid; grid-template-columns: 132px 58px 1fr 96px 78px;
  align-items: center; gap: 12px;
  padding: 9px 16px; border-bottom: 1px solid var(--border);
  cursor: pointer; background: none; width: 100%; text-align: left;
  font: inherit; color: inherit;
}
.theme-row:last-child { border-bottom: none; }
.theme-row:hover { background: var(--surface-2); }
.theme-row.active { background: #fff4f2; box-shadow: inset 3px 0 0 var(--accent); }
.theme-name { font-weight: 600; font-size: 13px; }
.theme-count { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
/* 这两个是 span，必须显式块化，否则 inline 元素的宽高无效，条形图不可见 */
.theme-track { display: block; background: #eef0f3; height: 8px; border-radius: 999px; overflow: hidden; }
.theme-fill { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--accent), #ff9575); }
.theme-delta { font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; }
.theme-delta.up { color: var(--up); }
.theme-delta.down { color: var(--down); }
.theme-delta.flat { color: var(--muted); font-weight: 400; }
.theme-new { font-size: 11.5px; color: var(--muted); text-align: right; }
.theme-new b { color: var(--accent); }

/* ---------- 工具条 ---------- */
.toolbar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 10px 12px; margin-bottom: 12px;
}
.search { position: relative; flex: 1; min-width: 200px; }
.search input {
  width: 100%; padding: 7px 30px 7px 30px; font: inherit; font-size: 13px;
  border: 1px solid var(--border); border-radius: 7px; background: var(--surface-2);
}
.search input:focus { outline: none; border-color: var(--accent); background: #fff; }
.search .icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--muted); font-size: 12px; }
.search kbd {
  position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
  font: 11px monospace; color: var(--muted); background: #eef0f3;
  border-radius: 4px; padding: 1px 5px;
}
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip {
  font: inherit; font-size: 12px; padding: 5px 11px; cursor: pointer;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 999px; color: var(--muted); white-space: nowrap;
}
.chip:hover { color: var(--text); border-color: #cfd4da; }
.chip.on { background: var(--text); border-color: var(--text); color: #fff; font-weight: 600; }
.chip.on.accent { background: var(--accent); border-color: var(--accent); }
.sep { width: 1px; height: 22px; background: var(--border); }
.count { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.count b { color: var(--text); }
.reset { font: inherit; font-size: 12px; background: none; border: none; color: var(--accent); cursor: pointer; padding: 4px; }
.reset[hidden] { display: none; }

/* ---------- 产品表 ---------- */
/* 用 clip 而非 hidden：hidden 会创建滚动容器，使表头的 sticky 失效 */
.table-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); overflow: clip; }
table { width: 100%; border-collapse: collapse; }
thead th {
  /* 偏移量由 JS 按顶栏实测高度写入，顶栏会随窗口宽度换行改变高度 */
  position: sticky; top: var(--topbar-h, 56px); z-index: 10;
  background: var(--surface-2); border-bottom: 1px solid var(--border);
  padding: 8px 12px; text-align: left; font-size: 11.5px; font-weight: 600;
  color: var(--muted); text-transform: uppercase; letter-spacing: .04em; white-space: nowrap;
}
thead th.sortable { cursor: pointer; user-select: none; }
thead th.sortable:hover { color: var(--text); }
thead th .arrow { opacity: 0; margin-left: 3px; }
thead th.sorted .arrow { opacity: 1; color: var(--accent); }
tbody td { padding: 9px 12px; border-bottom: 1px solid var(--border); vertical-align: top; font-size: 13px; }
tbody tr:last-child td { border-bottom: none; }
tbody tr.item:hover { background: var(--surface-2); }
tbody tr.item { cursor: pointer; }
.c-idx { color: var(--muted); font-variant-numeric: tabular-nums; width: 34px; font-size: 12px; }
.c-name { min-width: 220px; }
.c-name a { font-weight: 600; text-decoration: none; }
.c-name a:hover { color: var(--accent); text-decoration: underline; }
.c-desc { color: var(--muted); font-size: 12px; margin-top: 2px; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
tr.open .c-desc { -webkit-line-clamp: unset; }
.c-meta { display: none; }
tr.open .c-meta:not(:empty) {
  display: block; margin-top: 5px; font-size: 11.5px; color: var(--muted);
  border-left: 2px solid var(--border); padding-left: 8px;
}
.badge {
  display: inline-block; font-size: 10.5px; font-weight: 700; padding: 1px 6px;
  border-radius: 4px; margin-left: 6px; vertical-align: 1px; white-space: nowrap;
}
.badge.new { background: var(--accent); color: #fff; }
.badge.multi { background: var(--up-bg); color: var(--up); }
.c-plat, .c-theme { font-size: 12px; color: var(--muted); white-space: nowrap; }
.c-heat { width: 132px; }
.heat-inner { display: flex; align-items: center; gap: 8px; }
.heat-track { flex: 1; background: #eef0f3; height: 6px; border-radius: 999px; overflow: hidden; min-width: 44px; }
.heat-fill { height: 100%; background: var(--accent); border-radius: 999px; }
.heat-fill.weak { background: #c9ced4; }
.heat-val { font-size: 12px; font-variant-numeric: tabular-nums; width: 24px; text-align: right; color: var(--muted); }
.c-raw { font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; width: 92px; }
.c-raw small { color: var(--muted); }
.c-delta { font-size: 12px; font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; width: 84px; }
.delta { font-weight: 700; }
.delta.up { color: var(--up); }
.delta.down { color: var(--down); }
.dash { color: #c2c8ce; }
.empty-state { padding: 44px 20px; text-align: center; color: var(--muted); font-size: 13px; }

/* ---------- 附录 ---------- */
.appendix { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; }
.panel h3 { margin: 0 0 10px; font-size: 13px; }
.panel ol, .panel ul { margin: 0; padding-left: 18px; }
.panel li { font-size: 12.5px; margin-bottom: 4px; }
.cloud { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 12px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 999px; padding: 3px 9px; }
.note { color: var(--muted); font-size: 12px; margin: 10px 0 0; }
.note b { color: var(--text); }
footer { margin-top: 44px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; text-align: center; }

@media (max-width: 860px) {
  .kpis { width: 100%; justify-content: space-between; gap: 10px; margin-left: 0; }
  .theme-row { grid-template-columns: 104px 48px 1fr 70px; }
  .theme-new { display: none; }
  .c-theme, .c-raw, .c-delta,
  .h-theme, .h-votes, .h-votes_delta { display: none; }
  thead th { top: 0; position: static; }
}
"""

JS = """
const DATA = JSON.parse(document.getElementById('product-data').textContent);
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

const state = { q: '', platform: null, theme: null, quick: 'all', sort: 'heat', dir: -1 };
const opened = new Set();

const COLLATOR = new Intl.Collator('zh-CN');
const fmt = n => n.toLocaleString('en-US');
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

const QUICK_FILTERS = {
  all: () => true,
  new: p => p.is_new,
  multi: p => p.also_on && p.also_on.length,
  heat: p => p.has_real_heat && p.heat >= 80,
  surge: p => p.votes_delta > 0,
};

function match(p) {
  if (state.platform && p.platform !== state.platform) return false;
  // 按主赛道筛选，保证结果条数与赛道热力里显示的数量一致
  if (state.theme && p.theme !== state.theme) return false;
  if (!QUICK_FILTERS[state.quick](p)) return false;
  if (state.q) {
    const hay = (p.name + ' ' + p.description + ' ' + p.author + ' ' +
                 p.theme_label + ' ' + p.platform_label).toLowerCase();
    // 空格分隔的多个词需要全部命中
    if (!state.q.split(/\\s+/).every(t => hay.includes(t))) return false;
  }
  return true;
}

function compare(a, b) {
  const k = state.sort;
  let r;
  if (k === 'name') r = COLLATOR.compare(a.name, b.name);
  else if (k === 'platform') r = COLLATOR.compare(a.platform_label, b.platform_label);
  else if (k === 'theme') r = COLLATOR.compare(a.theme_label, b.theme_label);
  else if (k === 'votes') r = (a.votes - b.votes) || (a.heat - b.heat);
  // 无动量数据的产品始终排在最后，不与"零增长"混为一谈
  else if (k === 'votes_delta') {
    const av = a.votes_delta, bv = b.votes_delta;
    if (av == null && bv == null) r = 0;
    else if (av == null) return 1;
    else if (bv == null) return -1;
    else r = av - bv;
  }
  else r = (a.heat - b.heat) || (a.votes - b.votes);
  // 排序键相同时用名称保证顺序稳定
  return (r || COLLATOR.compare(a.name, b.name)) * state.dir;
}

function rowHTML(p, i) {
  const weak = p.has_real_heat ? '' : ' weak';
  const raw = p.has_real_heat
    ? fmt(p.votes) + (p.comments ? ' <small>/ ' + fmt(p.comments) + '</small>' : '')
    : '<span class="dash">—</span>';
  const badges =
    (p.is_new ? '<span class="badge new">NEW</span>' : '') +
    (p.also_on && p.also_on.length ? '<span class="badge multi">跨平台</span>' : '');

  return '<tr class="item' + (opened.has(p.id) ? ' open' : '') + '" data-id="' + esc(p.id) + '">' +
    '<td class="c-idx">' + (i + 1) + '</td>' +
    '<td class="c-name"><a href="' + esc(p.url) + '" target="_blank" rel="noopener">' +
      esc(p.name) + '</a>' + badges +
      '<div class="c-desc">' + esc(p.description) + '</div>' +
      '<div class="c-meta">' + trackHTML(p) + '</div></td>' +
    '<td class="c-plat">' + esc(p.platform_label) + '</td>' +
    '<td class="c-theme">' + esc(p.theme_label) + '</td>' +
    '<td class="c-heat"><div class="heat-inner"><div class="heat-track">' +
      '<div class="heat-fill' + weak + '" style="width:' + p.heat + '%"></div></div>' +
      '<span class="heat-val">' + p.heat + '</span></div></td>' +
    '<td class="c-raw">' + raw + '</td>' +
    '<td class="c-delta">' + deltaHTML(p) + '</td></tr>';
}

function deltaHTML(p) {
  if (p.votes_delta === null || p.votes_delta === undefined) {
    return '<span class="dash">—</span>';
  }
  if (p.votes_delta === 0) return '<span class="dash">0</span>';
  const up = p.votes_delta > 0;
  return '<span class="delta ' + (up ? 'up' : 'down') + '">' +
    (up ? '↑' : '↓') + fmt(Math.abs(p.votes_delta)) + '</span>';
}

// 展开行里补充"在榜多久"，判断是持续受关注还是一次性曝光
function trackHTML(p) {
  const bits = [];
  if (p.appearances >= 1) {
    bits.push('此前已出现 ' + p.appearances + ' 次');
    if (p.first_seen) bits.push('最早见于 ' + esc(p.first_seen.slice(5, 10)));
  } else if (p.is_new) {
    bits.push('本次首次出现');
  }
  if (p.also_on && p.also_on.length) bits.push('同时出现在 ' + p.also_on.length + ' 个其他平台');
  if (!p.has_real_heat) bits.push('该平台无公开票数，热度分按榜单位次估算');
  return bits.join(' · ');
}

function render() {
  const rows = DATA.filter(match).sort(compare);
  const tbody = $('#rows');

  tbody.innerHTML = rows.length
    ? rows.map(rowHTML).join('')
    : '<tr><td colspan="7" class="empty-state">没有匹配的产品。' +
      '<button class="reset" data-act="reset">清除筛选</button></td></tr>';

  $('#count').innerHTML = '<b>' + rows.length + '</b> / ' + DATA.length + ' 个产品';

  const active = state.q || state.platform || state.theme || state.quick !== 'all';
  $('#reset').hidden = !active;

  $$('.chip[data-quick]').forEach(c => c.classList.toggle('on', c.dataset.quick === state.quick));
  $$('.chip[data-platform]').forEach(c =>
    c.classList.toggle('on', c.dataset.platform === state.platform));
  $$('.theme-row').forEach(r => r.classList.toggle('active', r.dataset.theme === state.theme));
  $$('thead th.sortable').forEach(th => {
    const on = th.dataset.sort === state.sort;
    th.classList.toggle('sorted', on);
    $('.arrow', th).textContent = on ? (state.dir < 0 ? '↓' : '↑') : '↕';
  });
}

function setSort(key) {
  if (state.sort === key) {
    state.dir = -state.dir;
  } else {
    state.sort = key;
    // 文本列默认升序，数值列默认降序
    state.dir = (key === 'name' || key === 'platform' || key === 'theme') ? 1 : -1;
  }
  render();
}

function reset() {
  state.q = '';
  state.platform = null;
  state.theme = null;
  state.quick = 'all';
  $('#q').value = '';
  render();
}

document.addEventListener('click', e => {
  const el = e.target.closest('[data-quick],[data-platform],[data-theme],[data-sort],[data-act],tr.item');
  if (!el) return;

  if (el.dataset.act === 'reset') return reset();

  if (el.dataset.quick) {
    state.quick = state.quick === el.dataset.quick ? 'all' : el.dataset.quick;
  } else if (el.dataset.platform) {
    state.platform = state.platform === el.dataset.platform ? null : el.dataset.platform;
  } else if (el.dataset.theme) {
    state.theme = state.theme === el.dataset.theme ? null : el.dataset.theme;
    if (state.theme) $('#explorer').scrollIntoView({ block: 'start' });
  } else if (el.dataset.sort) {
    return setSort(el.dataset.sort);
  } else if (el.classList.contains('item')) {
    // 点击行展开完整描述，但不要拦截产品链接
    if (e.target.closest('a')) return;
    const id = el.dataset.id;
    opened.has(id) ? opened.delete(id) : opened.add(id);
    el.classList.toggle('open');
    return;
  }
  render();
});

$('#q').addEventListener('input', e => {
  state.q = e.target.value.trim().toLowerCase();
  render();
});

function syncTopbarHeight() {
  const h = $('.topbar').offsetHeight;
  document.documentElement.style.setProperty('--topbar-h', h + 'px');
}
window.addEventListener('resize', syncTopbarHeight);
syncTopbarHeight();

document.addEventListener('keydown', e => {
  const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName);
  if (e.key === '/' && !typing) { e.preventDefault(); $('#q').focus(); }
  else if (e.key === 'Escape') { reset(); $('#q').blur(); }
  else if (e.key === 'n' && !typing) {
    state.quick = state.quick === 'new' ? 'all' : 'new';
    render();
  }
});

render();
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>产品趋势看板 · __TIME__</title>
<style>__CSS__</style>
</head>
<body>
<div class="topbar"><div class="topbar-inner">
  <div class="brand">产品趋势看板<span>__TIME__</span></div>
  <div class="kpis">__KPIS__</div>
</div></div>

<div class="wrap">
__SIGNALS__
__THEMES__
__EXPLORER__
__APPENDIX__
<footer>Product Tracker 自动生成 · 快捷键：<kbd>/</kbd> 搜索 · <kbd>n</kbd> 只看新品 · <kbd>Esc</kbd> 清除筛选</footer>
</div>

<script type="application/json" id="product-data">__DATA__</script>
<script>__JS__</script>
</body>
</html>
"""


class ReportGenerator:
    """报告生成器"""

    def __init__(self, config: Dict):
        self.config = config
        self.output_dir = Path(config.get('reports_dir', './reports'))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, analysis_result, format: str = 'html') -> str:
        """生成分析报告，返回文件路径"""
        if format not in SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported format: {format}. Supported: {', '.join(SUPPORTED_FORMATS)}"
            )

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        suffix = {'html': 'html', 'json': 'json', 'markdown': 'md'}[format]
        filepath = self.output_dir / f"report_{timestamp}.{suffix}"

        builder = {
            'html': self._generate_html,
            'json': self._generate_json,
            'markdown': self._generate_markdown,
        }[format]
        builder(analysis_result, filepath)

        logger.info(f"Report generated: {filepath}")
        return str(filepath)

    # ------------------------------------------------------------------ HTML

    def _generate_html(self, result, filepath: Path):
        generated_at = self._format_time(result.timestamp)

        html = TEMPLATE
        for token, value in (
            ('__TIME__', escape(generated_at)),
            ('__CSS__', CSS),
            ('__KPIS__', self._html_kpis(result)),
            ('__SIGNALS__', self._html_signals(result)),
            ('__THEMES__', self._html_themes(result)),
            ('__EXPLORER__', self._html_explorer(result)),
            ('__APPENDIX__', self._html_appendix(result)),
            ('__DATA__', self._embed_json(result.products)),
            ('__JS__', JS),
        ):
            html = html.replace(token, value)

        filepath.write_text(html, encoding='utf-8')

    @staticmethod
    def _embed_json(payload) -> str:
        """内联 JSON，转义尖括号避免提前闭合 script 标签"""
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        return raw.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')

    def _html_kpis(self, result) -> str:
        history = result.history or {}
        items = [
            (str(result.total_products), '产品', False),
            (str(len(result.platforms)), '平台', False),
            (str(len(result.themes)), '赛道', False),
        ]
        if history.get('available'):
            items.append((str(history.get('new_count', 0)), '新发现', True))
        else:
            items.append(('首次', '无历史对比', False))

        rising = sum(1 for p in result.products if (p.get('votes_delta') or 0) > 0)
        if rising:
            items.append((str(rising), '热度上涨', True))

        return ''.join(
            f'<div class="kpi{" hl" if hl else ""}"><b>{escape(value)}</b>'
            f'<small>{escape(label)}</small></div>'
            for value, label, hl in items
        )

    def _html_signals(self, result) -> str:
        signals = result.signals or []
        if not signals:
            return ''

        cards = ''
        for signal in signals:
            direction = signal.get('direction', 'flat')
            icon = DIRECTION_ICONS.get(direction, DIRECTION_ICONS['flat'])
            theme = signal.get('theme')
            # 带赛道的信号可点击，直接把下方明细筛选到该赛道
            attrs = f' data-theme="{escape(theme, quote=True)}"' if theme else ''
            klass = f'signal {direction}' + (' clickable' if theme else '')

            evidence = ''.join(
                '<li>'
                f'<a href="{escape(item.get("url") or "#", quote=True)}" target="_blank" rel="noopener">'
                f'{escape(item.get("name", ""))}</a>'
                f'<em>{escape(item.get("note") or item.get("platform_label") or platform_label(item.get("platform", "")))}</em>'
                '</li>'
                for item in (signal.get('evidence') or [])[:3]
            )

            cards += (
                f'<div class="{klass}"{attrs}>'
                f'<div class="signal-top"><span class="dir {direction}">{icon}</span>'
                f'<h3>{escape(signal.get("title", ""))}</h3>'
                f'<span class="metric">{escape(str(signal.get("metric", "")))}</span></div>'
                f'<p>{escape(signal.get("detail", ""))}</p>'
                + (f'<ul class="evidence">{evidence}</ul>' if evidence else '')
                + '</div>'
            )

        return f"""<section id="signals">
<div class="sec-head"><h2>本次结论</h2><p>按重要性排序，点击卡片可在下方明细中筛选对应赛道</p></div>
<div class="signals">{cards}</div>
</section>"""

    def _html_themes(self, result) -> str:
        themes = result.themes or []
        if not themes:
            return ''

        max_count = max(t['count'] for t in themes)
        has_history = (result.history or {}).get('available')

        rows = ''
        for theme in themes:
            width = theme['count'] / max_count * 100
            delta = theme.get('delta')

            if delta is None:
                delta_html = '<span class="theme-delta flat">—</span>'
            elif delta > 0:
                delta_html = f'<span class="theme-delta up">▲ +{delta}pt</span>'
            elif delta < 0:
                delta_html = f'<span class="theme-delta down">▼ {delta}pt</span>'
            else:
                delta_html = '<span class="theme-delta flat">持平</span>'

            new_html = (
                f'<span class="theme-new"><b>{theme["new_count"]}</b> 新品</span>'
                if theme.get('new_count') else '<span class="theme-new"></span>'
            )

            rows += (
                f'<button class="theme-row" data-theme="{escape(theme["key"], quote=True)}">'
                f'<span class="theme-name">{escape(theme["label"])}</span>'
                f'<span class="theme-count">{theme["count"]} 个</span>'
                f'<span class="theme-track"><span class="theme-fill" style="width:{width:.1f}%"></span></span>'
                f'{delta_html}{new_html}</button>'
            )

        hint = (
            f"环比为与过去 {result.history.get('window_days')} 天的占比差（百分点）"
            if has_history else "环比需要至少一次历史数据，下次运行起显示"
        )
        return f"""<section id="themes">
<div class="sec-head"><h2>赛道热力</h2><p>{escape(hint)}，点击行可筛选明细</p></div>
<div class="themes">{rows}</div>
</section>"""

    def _html_explorer(self, result) -> str:
        meta = result.platform_meta or {}

        platform_chips = ''.join(
            f'<button class="chip" data-platform="{escape(key, quote=True)}">'
            f'{escape(info["label"])} <span class="theme-count">{info["count"]}</span></button>'
            for key, info in meta.items()
        )

        history = result.history or {}
        quick_chips = '<button class="chip accent" data-quick="all">全部</button>'
        if history.get('available'):
            quick_chips += (
                f'<button class="chip accent" data-quick="new">仅新品 '
                f'<span class="theme-count">{history.get("new_count", 0)}</span></button>'
            )
        multi_count = sum(1 for p in result.products if p.get('also_on'))
        if multi_count:
            quick_chips += (
                f'<button class="chip accent" data-quick="multi">跨平台 '
                f'<span class="theme-count">{multi_count}</span></button>'
            )
        quick_chips += '<button class="chip accent" data-quick="heat">高热度</button>'
        surge_count = sum(1 for p in result.products if (p.get('votes_delta') or 0) > 0)
        if surge_count:
            quick_chips += (
                f'<button class="chip accent" data-quick="surge">上涨中 '
                f'<span class="theme-count">{surge_count}</span></button>'
            )

        headers = [
            ('', '', False),
            ('产品', 'name', True),
            ('平台', 'platform', True),
            ('赛道', 'theme', True),
            ('热度分', 'heat', True),
            ('原始值', 'votes', True),
            ('较上次', 'votes_delta', True),
        ]
        head_html = ''
        for label, key, sortable in headers:
            if not sortable:
                head_html += f'<th>{escape(label)}</th>'
            else:
                # h-* 类名与 tbody 的 c-* 对应，窄屏隐藏列时表头一起隐藏，避免错位
                head_html += (
                    f'<th class="sortable h-{key}" data-sort="{key}">{escape(label)}'
                    '<span class="arrow">↕</span></th>'
                )

        return f"""<section id="explorer">
<div class="sec-head"><h2>产品明细</h2><p>热度分为平台内百分位（0-100），跨平台可比；原始值为各平台自己的口径；较上次为相对上一次采集的票数变化</p></div>
<div class="toolbar">
  <div class="search">
    <span class="icon">⌕</span>
    <input id="q" type="search" placeholder="搜索产品名、描述、作者、赛道…" autocomplete="off">
    <kbd>/</kbd>
  </div>
  <div class="chips">{quick_chips}</div>
  <span class="sep"></span>
  <div class="chips">{platform_chips}</div>
  <span class="sep"></span>
  <span class="count" id="count"></span>
  <button class="reset" id="reset" data-act="reset" hidden>清除筛选</button>
</div>
<div class="table-wrap">
<table><thead><tr>{head_html}</tr></thead><tbody id="rows"></tbody></table>
</div>
</section>"""

    def _html_appendix(self, result) -> str:
        panels = ''

        meta = result.platform_meta or {}
        if meta:
            items = ''.join(
                f'<li><b>{escape(info["label"])}</b>：{escape(info["heat_basis"])}'
                f'（{info["count"]} 个）</li>'
                for info in meta.values()
            )
            panels += (
                '<div class="panel"><h3>热度口径说明</h3>'
                f'<ul>{items}</ul>'
                '<p class="note">不同平台的热度量级不可直接比较，'
                '因此表中<b>热度分</b>是该产品在所属平台内的百分位。'
                '没有公开热度数据的平台按列表顺序折算，热度条为灰色。</p></div>'
            )

        keywords = result.auto_keywords or {}
        if keywords:
            chips = ''.join(
                f'<span class="tag">{escape(word)} {count}</span>'
                for word, count in list(keywords.items())[:22]
            )
            panels += (
                '<div class="panel"><h3>高频词</h3>'
                f'<div class="cloud">{chips}</div>'
                '<p class="note">不依赖预设词表，直接从本次产品名称与描述统计。</p></div>'
            )

        movers = (result.history or {}).get('keyword_movers') or []
        if movers:
            items = ''
            for m in movers[:8]:
                cls = 'up' if m['delta'] > 0 else 'down'
                sign = '+' if m['delta'] > 0 else ''
                items += (
                    f'<li>{escape(str(m["keyword"]))}：{m["previous"]}% → {m["current"]}% '
                    f'<span class="theme-delta {cls}">({sign}{m["delta"]}pt)</span></li>'
                )
            panels += f'<div class="panel"><h3>关键词环比</h3><ul>{items}</ul></div>'

        tags = result.tags or {}
        if tags:
            chips = ''.join(
                f'<span class="tag">{escape(str(tag))} {count}</span>'
                for tag, count in list(tags.items())[:18]
            )
            panels += f'<div class="panel"><h3>标签分布</h3><div class="cloud">{chips}</div></div>'

        if not panels:
            return ''
        return f"""<section id="appendix">
<div class="sec-head"><h2>附录</h2><p>口径与原始分布</p></div>
<div class="appendix">{panels}</div>
</section>"""

    # ------------------------------------------------------------------ JSON

    def _generate_json(self, result, filepath: Path):
        data = asdict(result) if is_dataclass(result) else dict(result.__dict__)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------- Markdown

    def _generate_markdown(self, result, filepath: Path):
        history = result.history or {}
        lines = [
            '# 产品趋势看板',
            '',
            f"**{self._format_time(result.timestamp)}** · {result.total_products} 个产品 · "
            f"{len(result.platforms)} 个平台 · {len(result.themes)} 个赛道"
            + (f" · 新发现 {history.get('new_count', 0)} 个" if history.get('available') else ''),
            '',
            '---',
            '',
            '## 本次结论',
            '',
        ]

        if result.signals:
            for signal in result.signals:
                icon = DIRECTION_ICONS.get(signal.get('direction', 'flat'))
                lines.append(
                    f"### {icon} {signal.get('title', '')} · {signal.get('metric', '')}"
                )
                lines.append('')
                lines.append(signal.get('detail', ''))
                evidence = signal.get('evidence') or []
                if evidence:
                    lines.append('')
                    for item in evidence[:3]:
                        label = item.get('platform_label') or platform_label(item.get('platform', ''))
                        note = f" · {item['note']}" if item.get('note') else ''
                        lines.append(
                            f"- [{item.get('name', '')}]({item.get('url') or '#'}) — {label}{note}"
                        )
                lines.append('')
        else:
            lines += ['_暂无足够数据生成结论_', '']

        lines += ['---', '', '## 赛道热力', '']
        if result.themes:
            lines += [
                '| 赛道 | 数量 | 占比 | 环比 | 新品 |',
                '|------|------|------|------|------|',
            ]
            for theme in result.themes:
                delta = theme.get('delta')
                if delta is None:
                    delta_text = '—'
                elif delta > 0:
                    delta_text = f'▲ +{delta}pt'
                elif delta < 0:
                    delta_text = f'▼ {delta}pt'
                else:
                    delta_text = '持平'
                lines.append(
                    f"| {theme['label']} | {theme['count']} | {theme['share']}% | "
                    f"{delta_text} | {theme['new_count'] or '—'} |"
                )
        else:
            lines.append('_暂无赛道数据_')

        lines += ['', '---', '', '## 值得看的产品', '']
        lines.append('热度分为平台内百分位（0-100），跨平台可比；原始值为各平台自己的口径。')
        lines.append('')
        lines += self._md_product_table(result.top_products[:15])

        if history.get('available') and history.get('new_products'):
            lines += [
                '', '---', '', f"## 本次新发现（{history.get('new_count', 0)} 个）", '',
            ]
            lines += self._md_product_table(history['new_products'][:15])

        lines += ['', '---', '', '## 各平台看点', '']
        for platform, items in (result.platform_highlights or {}).items():
            if not items:
                continue
            lines += [f"### {platform_label(platform)}", '']
            for item in items:
                heat = f" · 热度 {item.get('heat', 0)}"
                lines.append(
                    f"- [{item.get('name', '')}]({item.get('url') or '#'}){heat} — "
                    f"{(item.get('description') or '')[:100]}"
                )
            lines.append('')

        lines += ['---', '', '## 附录', '', '### 热度口径', '']
        for info in (result.platform_meta or {}).values():
            lines.append(f"- **{info['label']}**：{info['heat_basis']}（{info['count']} 个）")

        if result.auto_keywords:
            lines += ['', '### 高频词', '']
            lines.append(
                ' · '.join(f'`{w}` {c}' for w, c in list(result.auto_keywords.items())[:22])
            )

        movers = history.get('keyword_movers') or []
        if movers:
            lines += ['', '### 关键词环比', '']
            for m in movers[:8]:
                sign = '+' if m['delta'] > 0 else ''
                icon = '▲' if m['delta'] > 0 else '▼'
                lines.append(
                    f"- {icon} **{m['keyword']}**: {m['previous']}% → {m['current']}% "
                    f"({sign}{m['delta']}pt)"
                )

        if result.tags:
            lines += ['', '### 标签分布', '']
            lines.append(
                ' · '.join(f'`{t}` {c}' for t, c in list(result.tags.items())[:18])
            )

        lines += ['', '---', '', '*Product Tracker 自动生成*', '']
        filepath.write_text('\n'.join(lines), encoding='utf-8')

    @staticmethod
    def _md_product_table(products: List[Dict]) -> List[str]:
        if not products:
            return ['_暂无数据_']

        lines = [
            '| # | 产品 | 平台 | 赛道 | 热度分 | 原始值 |',
            '|---|------|------|------|--------|--------|',
        ]
        for i, p in enumerate(products, 1):
            # 单元格里的竖线会破坏 Markdown 表格结构
            name = (p.get('name') or '').replace('|', '\\|')
            if p.get('is_new'):
                name += ' 🆕'
            raw = f"{p.get('votes', 0):,}" if p.get('has_real_heat') else '—'
            lines.append(
                f"| {i} | [{name}]({p.get('url') or '#'}) | "
                f"{p.get('platform_label') or platform_label(p.get('platform', ''))} | "
                f"{p.get('theme_label', '')} | {p.get('heat', 0)} | {raw} |"
            )
        return lines

    @staticmethod
    def _format_time(timestamp: str) -> str:
        try:
            return datetime.fromisoformat(timestamp).strftime('%Y-%m-%d %H:%M')
        except (TypeError, ValueError):
            return str(timestamp)
