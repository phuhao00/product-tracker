"""
数据分析器
把原始采集数据加工成可用于决策的结构：赛道动量、归一化热度与决策信号
"""

import logging
import re
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from keywords import contains_keyword, normalize_text
from platforms import heat_basis, platform_label

from .themes import OTHER_THEME, classify, theme_label

logger = logging.getLogger(__name__)

# 自动关键词提取时忽略的高频无意义词
STOP_WORDS = frozenset("""
a an the and or but if then than that this these those for with without from into
onto over under about above below between of to in on at by as is are was were be
been being do does did doing have has had having will would can could should may
might must shall your you our we they it its their his her my me us them i
all any both each few more most other some such no nor not only own same so too very
s t don now new best free open using use used get make makes made your yours what
when where who whom which while how why here there via app apps tool tools product
products platform startup startups site website web online based simple easy fast
one two first ever every just like also more much many
""".split())

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-]{1,20}")
AI_KEYWORDS = ('ai', 'artificial intelligence', 'machine learning', 'llm', 'gpt', 'agent')
UNCATEGORIZED = 'Uncategorized'

# 赛道动量的判定阈值：占比变化（百分点）与最小样本量
MOMENTUM_THRESHOLD = 1.5
MOMENTUM_MIN_COUNT = 3
# 高热度新品的百分位门槛
HOT_NEW_PERCENTILE = 85
# 单品热度飙升的判定：既要有绝对增量，也要有相对涨幅
# 绝对值排除"1 票涨到 3 票"这类噪声，相对值让 HN 几十票的涨幅
# 不被 GitHub 上万星的基数淹没
SURGE_MIN_DELTA = 10
SURGE_MIN_GROWTH = 0.2


@dataclass
class AnalysisResult:
    """分析结果"""
    timestamp: str
    total_products: int
    platforms: Dict[str, int]
    top_products: List[Dict]
    categories: Dict[str, int]
    tags: Dict[str, int]
    trends: List[Dict]
    insights: List[str]
    platform_highlights: Dict[str, List[Dict]] = field(default_factory=dict)
    auto_keywords: Dict[str, int] = field(default_factory=dict)
    history: Dict = field(default_factory=dict)
    # 以下为决策看板所需数据
    products: List[Dict] = field(default_factory=list)
    platform_meta: Dict[str, Dict] = field(default_factory=dict)
    themes: List[Dict] = field(default_factory=list)
    signals: List[Dict] = field(default_factory=list)


class ProductAnalyzer:
    """产品数据分析器"""

    def __init__(self, config: Dict):
        self.config = config
        self.trend_window = config.get('trend_window_days', 7)
        self.keywords = config.get('keywords', [])
        self.top_limit = config.get('top_products_limit', 20)

    def analyze(
        self,
        products: List[Dict],
        history: Optional[List[Dict]] = None,
        product_stats: Optional[Dict[str, Dict]] = None,
    ) -> AnalysisResult:
        """分析产品数据

        history 为趋势窗口内打平的历史产品记录，用于识别新品与赛道动量。
        product_stats 为每个产品上一次的票数与在榜情况，用于计算单品热度动量。
        """
        if not products:
            return self._empty_result()

        history = history or []
        product_stats = product_stats or {}
        known_ids = {p.get('id') for p in history if p.get('id')}

        # 先做逐产品加工：赛道归属、平台内归一化热度、是否新品、单品动量
        enriched = self._enrich(
            products, known_ids, has_history=bool(history), product_stats=product_stats
        )
        platform_meta = self._build_platform_meta(enriched)

        platforms = self._count_platforms(enriched)
        categories = self._count_categories(enriched)
        tags = self._count_tags(enriched)
        auto_keywords = self._extract_auto_keywords(enriched)
        top_products = self._get_top_products(enriched, limit=self.top_limit)
        platform_highlights = self._get_platform_highlights(enriched)
        trends = self._detect_trends(enriched)
        themes = self._aggregate_themes(enriched, history)
        history_stats = self._compare_with_history(enriched, history, known_ids)
        signals = self._build_signals(enriched, themes, history_stats)
        insights = self._generate_insights(
            enriched, platforms, categories, tags, auto_keywords, history_stats
        )

        return AnalysisResult(
            timestamp=datetime.now().isoformat(timespec='seconds'),
            total_products=len(enriched),
            platforms=platforms,
            top_products=top_products,
            categories=categories,
            tags=tags,
            trends=trends,
            insights=insights,
            platform_highlights=platform_highlights,
            auto_keywords=auto_keywords,
            history=history_stats,
            products=[self._explorer_row(p) for p in enriched],
            platform_meta=platform_meta,
            themes=themes,
            signals=signals,
        )

    # ------------------------------------------------------------- 逐产品加工

    def _enrich(
        self,
        products: List[Dict],
        known_ids: set,
        has_history: bool,
        product_stats: Dict[str, Dict],
    ) -> List[Dict]:
        """为每个产品补充赛道、归一化热度、新品标记与单品动量"""
        enriched = []
        for product in products:
            item = dict(product)
            primary, matched = classify(
                item.get('name', ''), item.get('description', ''), item.get('tags') or []
            )
            item['theme'] = primary
            item['themes'] = matched
            # 无历史数据时无法判断是否新品，不做猜测
            item['is_new'] = has_history and item.get('id') not in known_ids
            enriched.append(item)

        self._assign_heat(enriched)
        self._assign_momentum(enriched, product_stats)
        return enriched

    @staticmethod
    def _assign_momentum(products: List[Dict], product_stats: Dict[str, Dict]) -> None:
        """计算单个产品相对上次出现时的票数变化

        只对有真实票数的平台计算。Product Hunt feed 与 BetaList 的"热度"来自列表
        顺序，位次波动不代表热度变化，给它们编造动量会误导判断。
        """
        for product in products:
            product['votes_delta'] = None
            product['appearances'] = 0
            product['first_seen'] = ''

            stats = product_stats.get(product.get('id'))
            if not stats:
                continue

            product['appearances'] = stats.get('appearances', 0)
            product['first_seen'] = stats.get('first_seen', '')

            if not product.get('has_real_heat'):
                continue
            prev = stats.get('prev_votes')
            if prev is None:
                continue
            product['votes_delta'] = (product.get('votes') or 0) - prev

    @staticmethod
    def _assign_heat(products: List[Dict]) -> None:
        """按平台内百分位计算热度分（0-100）

        各平台热度量级差异巨大（GitHub 上万星 vs HN 几十票），
        直接同榜排序会让高量级平台垄断榜首，因此归一化到平台内百分位。
        """
        by_platform = defaultdict(list)
        for product in products:
            by_platform[product.get('platform', 'unknown')].append(product)

        for platform, items in by_platform.items():
            votes = [p.get('votes') or 0 for p in items]
            has_votes = any(votes)

            if has_votes:
                signals = votes
            else:
                # 没有公开热度数据时，列表顺序是唯一可用的弱信号
                signals = [len(items) - i for i in range(len(items))]

            percentiles = ProductAnalyzer._percentiles(signals)
            basis = heat_basis(platform, has_votes)
            for product, score in zip(items, percentiles):
                product['heat'] = score
                product['heat_basis'] = basis
                product['has_real_heat'] = has_votes

    @staticmethod
    def _percentiles(values: List[float]) -> List[int]:
        """中位秩百分位，相同数值得到相同分数"""
        n = len(values)
        if n == 0:
            return []
        if n == 1:
            return [100]

        ordered = sorted(values)
        scores = []
        for value in values:
            lower = bisect_left(ordered, value)
            upper = bisect_right(ordered, value)
            ties = upper - lower
            scores.append(round((lower + 0.5 * ties) / n * 100))
        return scores

    @staticmethod
    def _build_platform_meta(products: List[Dict]) -> Dict[str, Dict]:
        """汇总各平台的热度口径，供报告标注"""
        meta: Dict[str, Dict] = {}
        for product in products:
            platform = product.get('platform', 'unknown')
            if platform not in meta:
                meta[platform] = {
                    'label': platform_label(platform),
                    'heat_basis': product.get('heat_basis', ''),
                    'has_real_heat': product.get('has_real_heat', False),
                    'count': 0,
                }
            meta[platform]['count'] += 1
        return meta

    @staticmethod
    def _explorer_row(product: Dict) -> Dict:
        """产品浏览器需要的精简字段"""
        return {
            'id': product.get('id', ''),
            'name': product.get('name', ''),
            'description': (product.get('description') or '')[:240],
            'url': product.get('url', ''),
            'platform': product.get('platform', ''),
            'platform_label': platform_label(product.get('platform', '')),
            'votes': product.get('votes') or 0,
            'comments': product.get('comments') or 0,
            'heat': product.get('heat', 0),
            'has_real_heat': product.get('has_real_heat', False),
            'theme': product.get('theme', ''),
            'theme_label': theme_label(product.get('theme', '')),
            'author': product.get('author', ''),
            'is_new': bool(product.get('is_new')),
            'votes_delta': product.get('votes_delta'),
            'appearances': product.get('appearances', 0),
            'first_seen': product.get('first_seen', ''),
            'also_on': (product.get('metadata') or {}).get('also_on') or [],
        }

    # ----------------------------------------------------------------- 赛道

    def _aggregate_themes(self, products: List[Dict], history: List[Dict]) -> List[Dict]:
        """按赛道聚合，并与历史窗口对比得出动量

        历史窗口里同一产品会重复出现多次（每次采集一份）。按 id 去重后再算占比，
        否则复采会把历史分母冲大，环比失去意义。
        """
        total = len(products)
        current = defaultdict(list)
        for product in products:
            current[product['theme']].append(product)

        previous_counts = Counter()
        for product in self._dedupe_history(history):
            primary, _ = classify(
                product.get('name', ''), product.get('description', ''),
                product.get('tags') or []
            )
            previous_counts[primary] += 1
        previous_total = sum(previous_counts.values())

        themes = []
        for key, items in current.items():
            share = round(len(items) / total * 100, 1)
            previous_share = (
                round(previous_counts[key] / previous_total * 100, 1)
                if previous_total else None
            )
            delta = round(share - previous_share, 1) if previous_share is not None else None

            # 证据优先展示有真实票数的产品，避免榜单位次冒充"赛道升温证明"
            ranked = sorted(
                items,
                key=lambda p: (
                    1 if p.get('has_real_heat') else 0,
                    p.get('heat', 0),
                    p.get('votes') or 0,
                ),
                reverse=True,
            )
            themes.append({
                'key': key,
                'label': theme_label(key),
                'count': len(items),
                'share': share,
                'previous_share': previous_share,
                'delta': delta,
                'new_count': sum(1 for p in items if p.get('is_new')),
                'platforms': dict(Counter(p.get('platform', '') for p in items).most_common()),
                'top': [self._summarize(p) for p in ranked[:5]],
            })

        # 数量优先排序，让主要赛道靠前
        themes.sort(key=lambda t: t['count'], reverse=True)
        return themes

    @staticmethod
    def _dedupe_history(history: List[Dict]) -> List[Dict]:
        """窗口内同一产品只保留最后一次出现，供赛道占比对比使用"""
        latest: Dict[str, Dict] = {}
        orphans: List[Dict] = []
        for product in history:
            product_id = product.get('id')
            if product_id:
                latest[product_id] = product
            else:
                orphans.append(product)
        return list(latest.values()) + orphans

    # ----------------------------------------------------------------- 信号

    def _build_signals(
        self, products: List[Dict], themes: List[Dict], history: Dict
    ) -> List[Dict]:
        """生成决策信号：回答"发生了什么变化、我该看什么" """
        has_history = history.get('available')
        signals: List[Dict] = []

        # 今日关注置顶：把热度、新品、动量、跨平台压成一张可行动的短名单
        signals.extend(self._watchlist_signal(products))

        if has_history:
            signals.extend(self._momentum_signals(themes))

        signals.extend(self._cross_platform_signal(products))
        signals.extend(self._surge_signal(products))

        if has_history:
            signals.extend(self._hot_new_signal(products))
            signals.extend(self._new_entrant_signal(themes))

        # 最大赛道始终给出，作为读者的方位感；若该赛道已有更强的信号则会被去重
        signals.extend(self._leader_signal(themes, has_history))

        return self._dedupe_by_theme(signals)[:6]

    @staticmethod
    def _leader_signal(themes: List[Dict], has_history: bool) -> List[Dict]:
        """当前最大赛道，给读者一个基本方位"""
        named = [t for t in themes if t['key'] != OTHER_THEME[0]]
        if not named:
            return []

        leader = named[0]
        detail = f"占本次采集的 {leader['share']}%（{leader['count']} 个产品）。"
        if not has_history:
            detail += '积累一次以上历史数据后即可显示环比变化。'

        return [{
            'kind': 'leader',
            'direction': 'flat',
            'title': f"最大赛道：{leader['label']}",
            'detail': detail,
            'metric': f"{leader['share']}%",
            'theme': leader['key'],
            'evidence': leader['top'][:3],
        }]

    @staticmethod
    def _dedupe_by_theme(signals: List[Dict]) -> List[Dict]:
        """同一赛道只保留最先命中的信号

        "X 升温"与"新品最集中于 X"往往指向同一件事、证据也相同，
        两张卡片并列只会稀释信息密度。跨平台等无赛道信号不受影响。
        """
        seen = set()
        unique = []
        for signal in signals:
            theme = signal.get('theme')
            if theme and theme in seen:
                continue
            if theme:
                seen.add(theme)
            unique.append(signal)
        return unique

    @staticmethod
    def _momentum_signals(themes: List[Dict]) -> List[Dict]:
        """赛道升温/降温

        "其他"是分类兜底桶，它的涨跌只反映分类覆盖度，不构成趋势结论。
        """
        movers = [
            t for t in themes
            if t['key'] != OTHER_THEME[0]
            and t['delta'] is not None
            and abs(t['delta']) >= MOMENTUM_THRESHOLD
            and t['count'] >= MOMENTUM_MIN_COUNT
        ]
        movers.sort(key=lambda t: abs(t['delta']), reverse=True)

        signals = []
        for theme in movers[:3]:
            rising = theme['delta'] > 0
            signals.append({
                'kind': 'momentum',
                'direction': 'up' if rising else 'down',
                'title': f"{theme['label']}{'升温' if rising else '降温'}",
                'detail': (
                    f"占比从 {theme['previous_share']}% 变为 {theme['share']}%"
                    f"（{'+' if rising else ''}{theme['delta']} 个百分点），"
                    f"本次共 {theme['count']} 个产品"
                    + (f"，其中 {theme['new_count']} 个是新品。" if theme['new_count'] else "。")
                ),
                'metric': f"{'+' if rising else ''}{theme['delta']}pt",
                'theme': theme['key'],
                'evidence': theme['top'][:3],
            })
        return signals

    def _cross_platform_signal(self, products: List[Dict]) -> List[Dict]:
        """同时出现在多个平台，是最强的热度信号"""
        multi = [p for p in products if (p.get('metadata') or {}).get('also_on')]
        if not multi:
            return []

        multi.sort(key=lambda p: p.get('heat', 0), reverse=True)
        return [{
            'kind': 'cross_platform',
            'direction': 'up',
            'title': f"{len(multi)} 个产品跨平台同时出现",
            'detail': (
                "同一产品被多个榜单同时收录，通常意味着真实热度而非单一平台的算法偏好，"
                "值得优先关注。"
            ),
            'metric': f"{len(multi)} 个",
            'theme': None,
            'evidence': [self._summarize(p) for p in multi[:3]],
        }]

    def _surge_signal(self, products: List[Dict]) -> List[Dict]:
        """相比上次采集正在加速上涨的产品

        按相对涨幅排序：GitHub 一万星涨 500 不如 HN 20 票涨到 80 有信息量。
        """
        surging = []
        for product in products:
            delta = product.get('votes_delta')
            if delta is None or delta < SURGE_MIN_DELTA:
                continue
            base = max((product.get('votes') or 0) - delta, 1)
            growth = delta / base
            if growth < SURGE_MIN_GROWTH:
                continue
            surging.append((growth, product))

        if not surging:
            return []

        surging.sort(key=lambda item: item[0], reverse=True)
        evidence = []
        for growth, product in surging[:3]:
            summary = self._summarize(product)
            summary['note'] = f"+{product['votes_delta']:,}（{growth:.0%}）"
            evidence.append(summary)

        return [{
            'kind': 'surge',
            'direction': 'up',
            'title': f"{len(surging)} 个产品热度加速上涨",
            'detail': (
                f"相比上一次采集，这些产品的票数/星数至少增加 {SURGE_MIN_DELTA} "
                f"且涨幅超过 {SURGE_MIN_GROWTH:.0%}，说明关注度仍在累积而非一次性曝光。"
            ),
            'metric': f"{len(surging)} 个",
            'theme': None,
            'evidence': evidence,
        }]

    def _watchlist_signal(self, products: List[Dict]) -> List[Dict]:
        """今日关注短名单：把分散信号压成 5 个现在就该点开的产品

        综合热度百分位、是否新品、是否跨平台、是否仍在上涨。
        无真实票数的平台略降权，但不排除——否则 PH/BetaList 前列新品永远进不来。
        """
        if len(products) < 3:
            return []

        scored = []
        for product in products:
            score = float(product.get('heat', 0))
            reasons = []
            if product.get('is_new'):
                score += 15
                reasons.append('新品')
            also_on = (product.get('metadata') or {}).get('also_on') or []
            if also_on:
                score += 20
                reasons.append('跨平台')
            delta = product.get('votes_delta')
            if delta is not None and delta > 0:
                score += min(25.0, 8 + delta / 40)
                reasons.append(f'+{delta:,}')
            if product.get('has_real_heat'):
                score += 5
            else:
                score *= 0.9
                if product.get('heat', 0) >= HOT_NEW_PERCENTILE:
                    reasons.append('榜单前列')
            if product.get('heat', 0) >= 90 and '热度高' not in reasons:
                reasons.append('热度高')
            scored.append((score, reasons, product))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[:5]
        if not top or top[0][0] < 50:
            return []

        evidence = []
        for score, reasons, product in top:
            summary = self._summarize(product)
            summary['note'] = ' · '.join(reasons[:2]) or product.get('platform_label', '')
            evidence.append(summary)

        return [{
            'kind': 'watchlist',
            'direction': 'up',
            'title': '今日关注',
            'detail': (
                '综合热度、新品、跨平台与上涨动量挑出的短名单，'
                '优先点开这些再决定是否深挖整张表。'
            ),
            'metric': f"{len(evidence)} 个",
            'theme': None,
            'evidence': evidence,
        }]

    def _hot_new_signal(self, products: List[Dict]) -> List[Dict]:
        """新品且在所属平台内热度靠前

        不强制要求真实票数：PH/BetaList 只有榜单位次，但榜单前列的新品
        仍是"每天看新产品"场景里最该看的信号。
        """
        hot_new = [
            p for p in products
            if p.get('is_new') and p.get('heat', 0) >= HOT_NEW_PERCENTILE
        ]
        if not hot_new:
            return []

        hot_new.sort(
            key=lambda p: (
                1 if p.get('has_real_heat') else 0,
                p.get('heat', 0),
            ),
            reverse=True,
        )
        real = sum(1 for p in hot_new if p.get('has_real_heat'))
        detail = (
            f"这些产品是本次首次出现，且在所属平台内热度百分位达到 "
            f"{HOT_NEW_PERCENTILE} 以上。"
        )
        if real and real < len(hot_new):
            detail += (
                f"其中 {real} 个有真实票数，其余来自按榜单位次估算热度的平台，"
                "请交叉验证。"
            )
        elif not real:
            detail += "当前命中的都来自无公开票数的平台，热度按榜单位次估算。"

        return [{
            'kind': 'hot_new',
            'direction': 'up',
            'title': f"{len(hot_new)} 个新品直接冲进平台前列",
            'detail': detail,
            'metric': f"{len(hot_new)} 个",
            'theme': None,
            'evidence': [self._summarize(p) for p in hot_new[:3]],
        }]

    @staticmethod
    def _new_entrant_signal(themes: List[Dict]) -> List[Dict]:
        """新品最集中的赛道，反映资源正在涌入的方向"""
        candidates = [
            t for t in themes
            if t['new_count'] >= 2 and t['key'] != OTHER_THEME[0]
        ]
        if not candidates:
            return []

        top = max(candidates, key=lambda t: t['new_count'])
        return [{
            'kind': 'new_entrants',
            'direction': 'up',
            'title': f"新品最集中于{top['label']}",
            'detail': (
                f"本次 {top['new_count']} 个新品落在该赛道"
                f"（占赛道内 {top['count']} 个产品的 "
                f"{round(top['new_count'] / top['count'] * 100)}%）。"
            ),
            'metric': f"{top['new_count']} 个新品",
            'theme': top['key'],
            'evidence': [p for p in top['top'] if p.get('is_new')][:3] or top['top'][:3],
        }]

    # ------------------------------------------------------------- 基础统计

    def _count_platforms(self, products: List[Dict]) -> Dict[str, int]:
        """统计各平台产品数量"""
        return dict(Counter(p.get('platform', 'unknown') for p in products).most_common())

    def _count_categories(self, products: List[Dict]) -> Dict[str, int]:
        """统计各分类产品数量"""
        counter = Counter(p.get('category') or UNCATEGORIZED for p in products)
        return dict(counter.most_common(15))

    def _count_tags(self, products: List[Dict]) -> Dict[str, int]:
        """统计标签频率"""
        all_tags = []
        for p in products:
            tags = p.get('tags')
            if isinstance(tags, list):
                all_tags.extend(tags)
        return dict(Counter(all_tags).most_common(20))

    def _extract_auto_keywords(self, products: List[Dict], limit: int = 25) -> Dict[str, int]:
        """从名称与描述中自动提取高频关键词

        与配置的 keywords 不同，这里不预设词表，用于发现配置里没想到的新热点。
        """
        counter = Counter()
        for product in products:
            text = f"{product.get('name', '')} {product.get('description', '')}".lower()
            # 每个产品内同一词只计一次，避免长描述里的重复词刷高排名
            words = {
                token for token in TOKEN_RE.findall(text)
                if len(token) > 2 and token not in STOP_WORDS
            }
            counter.update(words)

        return {word: count for word, count in counter.most_common(limit) if count > 1}

    def _get_top_products(self, products: List[Dict], limit: int = 20) -> List[Dict]:
        """获取热门产品

        用归一化热度排序，避免高量级平台垄断榜首。
        """
        ranked = sorted(
            products,
            key=lambda x: (x.get('heat', 0), x.get('votes') or 0),
            reverse=True
        )
        return [self._summarize(p) for p in ranked[:limit]]

    def _get_platform_highlights(self, products: List[Dict], per_platform: int = 5) -> Dict:
        """各平台单独的热门榜"""
        grouped = defaultdict(list)
        for product in products:
            grouped[product.get('platform', 'unknown')].append(product)

        highlights = {}
        for platform, items in grouped.items():
            ranked = sorted(items, key=lambda x: x.get('heat', 0), reverse=True)
            highlights[platform] = [self._summarize(p) for p in ranked[:per_platform]]
        return highlights

    @staticmethod
    def _summarize(product: Dict) -> Dict:
        """裁剪为报告需要的字段"""
        return {
            'name': product.get('name', ''),
            'platform': product.get('platform', ''),
            'platform_label': platform_label(product.get('platform', '')),
            'votes': product.get('votes') or 0,
            'comments': product.get('comments') or 0,
            'heat': product.get('heat', 0),
            'has_real_heat': product.get('has_real_heat', False),
            'description': (product.get('description') or '')[:160],
            'url': product.get('url', ''),
            'author': product.get('author', ''),
            'theme': product.get('theme', ''),
            'theme_label': theme_label(product.get('theme', '')),
            'is_new': bool(product.get('is_new')),
        }

    def _detect_trends(self, products: List[Dict]) -> List[Dict]:
        """统计配置关键词的出现热度"""
        total = len(products)
        keyword_counts = defaultdict(int)

        for product in products:
            text = normalize_text(
                f"{product.get('name', '')} {product.get('description', '')}"
            )
            for keyword in self.keywords:
                if contains_keyword(text, keyword):
                    keyword_counts[keyword] += 1

        trends = [
            {
                'keyword': keyword,
                'count': count,
                'percentage': round(count / total * 100, 1),
            }
            for keyword, count in sorted(
                keyword_counts.items(), key=lambda x: x[1], reverse=True
            )
            if count > 0
        ]
        return trends[:10]

    def _compare_with_history(
        self, products: List[Dict], history: List[Dict], known_ids: set
    ) -> Dict:
        """与趋势窗口内的历史数据对比"""
        if not history:
            return {
                'window_days': self.trend_window,
                'available': False,
                'historical_products': 0,
                'new_products': [],
                'new_count': len(products),
                'returning_count': 0,
                'keyword_movers': [],
            }

        new_products = [p for p in products if p.get('is_new')]
        new_products.sort(key=lambda p: p.get('heat', 0), reverse=True)

        return {
            'window_days': self.trend_window,
            'available': True,
            'historical_products': len(known_ids),
            'new_products': [self._summarize(p) for p in new_products[:20]],
            'new_count': len(new_products),
            'returning_count': len(products) - len(new_products),
            'keyword_movers': self._keyword_movers(products, history),
        }

    def _keyword_movers(self, products: List[Dict], history: List[Dict]) -> List[Dict]:
        """对比本次与历史的关键词占比，找出上升/下降最快的词"""
        current = self._keyword_share(products)
        previous = self._keyword_share(history)

        movers = []
        for keyword in set(current) | set(previous):
            now = current.get(keyword, 0.0)
            before = previous.get(keyword, 0.0)
            delta = round(now - before, 1)
            if abs(delta) >= 1.0:
                movers.append({
                    'keyword': keyword,
                    'current': now,
                    'previous': before,
                    'delta': delta,
                })

        movers.sort(key=lambda m: abs(m['delta']), reverse=True)
        return movers[:10]

    def _keyword_share(self, products: List[Dict]) -> Dict[str, float]:
        """配置关键词在给定集合中的出现占比（%）"""
        if not products:
            return {}

        counts = defaultdict(int)
        for product in products:
            text = normalize_text(
                f"{product.get('name', '')} {product.get('description', '')}"
            )
            for keyword in self.keywords:
                if contains_keyword(text, keyword):
                    counts[keyword] += 1

        total = len(products)
        return {kw: round(count / total * 100, 1) for kw, count in counts.items()}

    def _generate_insights(
        self,
        products: List[Dict],
        platforms: Dict[str, int],
        categories: Dict[str, int],
        tags: Dict[str, int],
        auto_keywords: Dict[str, int],
        history: Dict,
    ) -> List[str]:
        """生成分析洞察"""
        insights = []
        total = len(products)

        if platforms:
            top_platform = max(platforms, key=platforms.get)
            insights.append(
                f"📊 主要数据来源: {platform_label(top_platform)} "
                f"({platforms[top_platform]} 个产品, 占 {platforms[top_platform] / total * 100:.0f}%)"
            )

        # 未分类只说明数据源没提供分类，作为"最热门分类"没有意义
        named_categories = {
            name: count for name, count in categories.items() if name != UNCATEGORIZED
        }
        if named_categories:
            top_category = max(named_categories, key=named_categories.get)
            insights.append(
                f"🏷️ 最热门分类: {top_category} ({named_categories[top_category]} 个产品)"
            )

        if tags:
            insights.append(f"🔥 热门标签: {', '.join(list(tags)[:5])}")

        if auto_keywords:
            insights.append(f"🔎 高频词: {', '.join(list(auto_keywords)[:8])}")

        # 只在有票数的平台上统计，否则会被 votes=0 的平台拉低平均值
        voted = [p.get('votes') or 0 for p in products if (p.get('votes') or 0) > 0]
        if voted:
            insights.append(
                f"📈 热度统计: {len(voted)} 个产品有票数数据, "
                f"平均 {sum(voted) / len(voted):.0f}, 最高 {max(voted)}"
            )

        ai_count = sum(
            1 for p in products
            if any(
                contains_keyword(
                    normalize_text(f"{p.get('name', '')} {p.get('description', '')}"), kw
                )
                for kw in AI_KEYWORDS
            )
        )
        if ai_count:
            insights.append(
                f"🤖 AI相关产品: {ai_count} 个 ({ai_count / total * 100:.1f}%)"
            )

        if history.get('available'):
            insights.append(
                f"🆕 对比过去 {history['window_days']} 天: 新增 {history['new_count']} 个, "
                f"复现 {history['returning_count']} 个"
            )
        else:
            insights.append("ℹ️ 首次运行，暂无历史数据可对比（下次运行起将显示趋势变化）")

        return insights

    def _empty_result(self) -> AnalysisResult:
        """返回空分析结果"""
        return AnalysisResult(
            timestamp=datetime.now().isoformat(timespec='seconds'),
            total_products=0,
            platforms={},
            top_products=[],
            categories={},
            tags={},
            trends=[],
            insights=["⚠️ 没有数据可分析：请检查网络或 config.yaml 中的平台开关"],
        )
