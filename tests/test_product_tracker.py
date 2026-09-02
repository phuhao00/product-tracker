"""
离线单元测试
覆盖解析、去重、调度与报告生成，全部不依赖网络
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from analyzers import ProductAnalyzer, ReportGenerator
from analyzers.themes import classify, theme_label
from keywords import contains_keyword, match_keywords, normalize_text
from collectors import Product, available_platforms, get_collector
from collectors.betalist import BetaListCollector
from collectors.github_trending import GitHubTrendingCollector
from collectors.hackernews import HackerNewsCollector
from collectors.producthunt import ProductHuntCollector
from main import ProductTracker, normalize_name, normalize_url
from scheduler import CronExpression, Scheduler


# --------------------------------------------------------------- 关键词匹配

@pytest.mark.parametrize('text', [
    'Available now',
    'Send me an email',
    'We maintain the chain',
    'Certain things',
])
def test_ai_keyword_does_not_match_substrings(text):
    # 子串匹配会让 available/email/maintain/certain 全部误判为 AI 产品
    assert not contains_keyword(normalize_text(text), 'AI')


@pytest.mark.parametrize('text', [
    'An AI agent',
    'ai-powered search',
    'Built with (AI)',
    'AI.',
])
def test_ai_keyword_matches_real_mentions(text):
    assert contains_keyword(normalize_text(text), 'AI')


def test_go_keyword_ignores_longer_words():
    assert contains_keyword(normalize_text('Written in Go'), 'go')
    assert not contains_keyword(normalize_text('Google is going there'), 'go')


def test_hyphenated_text_matches_spaced_keyword():
    assert contains_keyword(normalize_text('an open-source plugin'), 'open source')
    assert contains_keyword(normalize_text('open source tool'), 'open source')


def test_match_keywords_preserves_given_order():
    text = 'An AI automation tool for developer tools'
    assert match_keywords(text, ['developer tools', 'AI', 'SaaS']) == ['developer tools', 'AI']


# --------------------------------------------------------------- 采集器解析

PH_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>tag:www.producthunt.com,2005:Post/1222307</id>
    <published>2026-08-13T09:30:37-07:00</published>
    <link rel="alternate" type="text/html" href="https://www.producthunt.com/products/widget"/>
    <title>Widget &amp; Co</title>
    <content type="html">&lt;p&gt;A tool that does things.&lt;/p&gt;&lt;p&gt;&lt;a&gt;Discussion&lt;/a&gt;&lt;/p&gt;</content>
    <author><name>Jane Doe</name></author>
  </entry>
</feed>
"""


def test_producthunt_parses_atom_entry():
    from xml.etree import ElementTree

    collector = ProductHuntCollector({'name': 'Product Hunt'})
    root = ElementTree.fromstring(PH_FEED)
    entry = root.find('{http://www.w3.org/2005/Atom}entry')

    product = collector._parse_entry(entry, rank=1)

    assert product.id == 'ph_1222307'
    assert product.name == 'Widget & Co'
    assert product.description == 'A tool that does things.'
    assert product.url == 'https://www.producthunt.com/products/widget'
    assert product.author == 'Jane Doe'
    assert product.metadata['feed_rank'] == 1


def test_producthunt_skips_discussion_paragraph():
    collector = ProductHuntCollector({'name': 'Product Hunt'})
    content = '<p><a>Discussion</a> | <a>Link</a></p>'
    assert collector._extract_description(content) == ''


def test_hackernews_parses_search_hit_and_decodes_entities():
    collector = HackerNewsCollector({'name': 'Hacker News'})
    hit = {
        'objectID': '49519978',
        'title': 'Show HN: Floe – an open-source plugin',
        'url': 'https://floe.audio/',
        'story_text': '<p>I&#x27;m Sam, I make   sample libraries.</p>',
        'points': 19,
        'num_comments': 4,
        'author': 'sam',
        'created_at': '2026-09-01T10:02:09Z',
    }

    product = collector._parse_search_hit(hit)

    assert product.id == 'hn_49519978'
    # "Show HN:" 前缀应被剥离
    assert product.name == 'Floe – an open-source plugin'
    # HTML 实体与标签应被还原/剥离，空白折叠
    assert product.description == "I'm Sam, I make sample libraries."
    assert product.votes == 19
    assert product.comments == 4
    assert 'Open Source' in product.tags


def test_hackernews_falls_back_to_name_when_no_body():
    collector = HackerNewsCollector({'name': 'Hacker News'})
    product = collector._parse_search_hit({'objectID': '1', 'title': 'Show HN: Thing'})

    assert product.name == 'Thing'
    assert product.description == 'Thing'
    assert product.url == 'https://news.ycombinator.com/item?id=1'


def test_hackernews_rejects_incomplete_hit():
    collector = HackerNewsCollector({'name': 'Hacker News'})
    assert collector._parse_search_hit({'objectID': '1'}) is None
    assert collector._parse_search_hit({'title': 'No id'}) is None


BETALIST_HTML = """
<div class="grid">
  <div class="relative flex gap-3 border">
    <div class="shrink-0"><img src="https://img.example/logo.png"/></div>
    <div class="block">
      <a href="/startups/applyboost">
        <div class="font-medium text-gray-900">ApplyBoost</div>
      </a>
      <div class="text-gray-600">Turn any job description into ATS-ready resume bullets</div>
    </div>
    <a class="absolute inset-0" href="/startups/applyboost"></a>
  </div>
</div>
"""


def test_betalist_aggregates_duplicate_links_per_product():
    collector = BetaListCollector({'name': 'BetaList'})
    products = collector._parse_listing(BETALIST_HTML)

    # 同一产品有两个链接（标题 + 整卡覆盖层），应合并为一条
    assert len(products) == 1
    product = products[0]
    assert product.id == 'bl_applyboost'
    assert product.name == 'ApplyBoost'
    assert product.description.startswith('Turn any job description')
    assert product.url == 'https://betalist.com/startups/applyboost'
    assert product.image == 'https://img.example/logo.png'


BETALIST_BOOSTED_HTML = """
<div class="relative flex gap-3 border">
  <div><img src="/logo.png"/></div>
  <div class="block">
    <a href="/startups/talmaara">
      <div class="font-medium">Talmaara<span>BOOSTED</span></div>
    </a>
    <div class="text-gray-600">Talmaara.com is a marketplace for learners BOOSTED</div>
  </div>
</div>
"""


def test_betalist_strips_promotion_badges():
    collector = BetaListCollector({'name': 'BetaList'})
    product = collector._parse_listing(BETALIST_BOOSTED_HTML)[0]

    # 推广徽章与正文连在一起，不应污染名称与描述
    assert product.name == 'Talmaara'
    assert 'BOOSTED' not in product.description
    assert product.description.startswith('Talmaara.com is a marketplace')
    # 站内相对路径的图片应补全为绝对地址
    assert product.image == 'https://betalist.com/logo.png'


GITHUB_HTML = """
<article class="Box-row">
  <h2><a href="/acme/toolkit">acme / toolkit</a></h2>
  <p>A developer toolkit &amp; CLI</p>
  <span itemprop="programmingLanguage">Rust</span>
  <a href="/acme/toolkit/stargazers">12,345</a>
  <a href="/acme/toolkit/forks">678</a>
  <span class="d-inline-block float-sm-right">1,234 stars this week</span>
</article>
"""


def test_github_trending_uses_period_stars_as_votes():
    collector = GitHubTrendingCollector({'name': 'GitHub Trending'})
    products = collector._parse_trending(GITHUB_HTML, 'weekly')

    assert len(products) == 1
    product = products[0]
    assert product.id == 'gh_acme_toolkit'
    assert product.name == 'toolkit'
    assert product.author == 'acme'
    # 用周期内新增星数而非总星数衡量当下热度
    assert product.votes == 1234
    assert product.metadata['total_stars'] == 12345
    assert product.metadata['forks'] == 678
    assert product.category == 'Rust'


def test_get_collector_rejects_unknown_platform():
    assert 'github_trending' in available_platforms()
    with pytest.raises(ValueError, match='Unknown platform'):
        get_collector('nope', {})


# ------------------------------------------------------------------- 去重

def make_product(pid, name, url, platform, votes=0, description=''):
    return Product(
        id=pid,
        name=name,
        description=description or name,
        url=url,
        platform=platform,
        votes=votes,
    )


def test_normalize_url_strips_scheme_www_and_tracking():
    assert normalize_url('https://www.Example.com/tool/') == 'example.com/tool'
    assert normalize_url('http://example.com/x?utm_source=ph') == 'example.com/x'
    assert normalize_url('') == ''


def test_normalize_name_keeps_alphanumerics_only():
    assert normalize_name('Widget & Co!') == 'widgetco'


def test_deduplicate_merges_same_url_across_platforms():
    products = [
        make_product('hn_1', 'Floe', 'https://floe.audio/', 'hackernews', votes=19),
        make_product('ph_2', 'Floe', 'https://floe.audio', 'producthunt', votes=0),
    ]

    merged = ProductTracker.deduplicate(products)

    assert len(merged) == 1
    assert merged[0].platform == 'hackernews'
    assert merged[0].metadata['also_on'] == ['producthunt']


def test_deduplicate_keeps_highest_votes_and_longest_description():
    products = [
        make_product('a', 'Toolkit', 'https://a.example', 'producthunt', description='short'),
        make_product('b', 'Toolkit', 'https://b.example', 'hackernews', votes=42,
                     description='a much longer description'),
    ]

    merged = ProductTracker.deduplicate(products)

    assert len(merged) == 1
    assert merged[0].votes == 42
    assert merged[0].description == 'a much longer description'


def test_deduplicate_does_not_merge_short_names_from_different_urls():
    products = [
        make_product('a', 'AI', 'https://a.example', 'producthunt'),
        make_product('b', 'AI', 'https://b.example', 'betalist'),
    ]

    # 名称过短时撞名概率高，不应合并
    assert len(ProductTracker.deduplicate(products)) == 2


# --------------------------------------------------------------- 历史窗口

def _write_snapshot(data_dir, stamp, products):
    payload = {
        'collected_at': f"2026-09-0{stamp}T10:00:00",
        'total': len(products),
        'products': products,
    }
    path = data_dir / f"products_2026090{stamp}_100000.json"
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def _tracker(tmp_path):
    return ProductTracker({
        'app': {'data_dir': str(tmp_path / 'data'), 'reports_dir': str(tmp_path / 'reports')},
        'analysis': {'trend_window_days': 7},
    })


def test_load_history_tracks_previous_votes_per_product(tmp_path):
    tracker = _tracker(tmp_path)
    _write_snapshot(tracker.data_dir, 1, [{'id': 'a', 'votes': 10}])
    _write_snapshot(tracker.data_dir, 2, [{'id': 'a', 'votes': 25}, {'id': 'b', 'votes': 4}])

    window = tracker.load_history()

    # prev_votes 应停在最近一次快照，而不是最早那次
    assert window.product_stats['a']['prev_votes'] == 25
    assert window.product_stats['a']['appearances'] == 2
    assert window.product_stats['a']['first_seen'].startswith('2026-09-01')
    assert window.product_stats['b']['prev_votes'] == 4


def test_load_history_excludes_the_current_snapshot(tmp_path):
    tracker = _tracker(tmp_path)
    _write_snapshot(tracker.data_dir, 1, [{'id': 'a', 'votes': 10}])
    latest = _write_snapshot(tracker.data_dir, 2, [{'id': 'a', 'votes': 25}])

    window = tracker.load_history(exclude=latest)

    assert window.snapshots == 1
    assert window.product_stats['a']['prev_votes'] == 10


def test_load_history_excludes_by_real_path_not_string_identity(tmp_path, monkeypatch):
    """排除失败会让本次快照成为自己的历史，动量恒为 0 且不报错"""
    tracker = _tracker(tmp_path)
    _write_snapshot(tracker.data_dir, 1, [{'id': 'a', 'votes': 10}])
    latest = _write_snapshot(tracker.data_dir, 2, [{'id': 'a', 'votes': 25}])

    monkeypatch.chdir(tracker.data_dir)
    window = tracker.load_history(exclude=Path(latest.name))

    assert window.snapshots == 1
    assert window.product_stats['a']['prev_votes'] == 10


def test_load_history_skips_unreadable_snapshots(tmp_path):
    tracker = _tracker(tmp_path)
    _write_snapshot(tracker.data_dir, 1, [{'id': 'a', 'votes': 10}])
    (tracker.data_dir / 'products_20260902_100000.json').write_text('{oops', encoding='utf-8')

    window = tracker.load_history()

    assert window.snapshots == 1
    assert 'a' in window.product_stats


# ------------------------------------------------------------------- 分析

@pytest.fixture
def sample_products():
    return [
        {
            'id': 'gh_1', 'name': 'agent-kit', 'description': 'An AI agent toolkit',
            'url': 'https://github.com/a/agent-kit', 'platform': 'github_trending',
            'votes': 900, 'comments': 0, 'category': 'Python', 'tags': ['open-source', 'python'],
        },
        {
            'id': 'hn_2', 'name': 'Notes app', 'description': 'A productivity tool for notes',
            'url': 'https://notes.example', 'platform': 'hackernews',
            'votes': 40, 'comments': 12, 'category': 'Show HN', 'tags': ['Productivity'],
        },
        {
            'id': 'ph_3', 'name': 'Deploy bot', 'description': 'automation for SaaS teams',
            'url': 'https://deploy.example', 'platform': 'producthunt',
            'votes': 0, 'comments': 0, 'category': '', 'tags': [],
        },
    ]


@pytest.fixture
def analyzer():
    return ProductAnalyzer({
        'trend_window_days': 7,
        'keywords': ['AI', 'automation', 'productivity', 'SaaS'],
    })


def test_analyze_counts_and_ranks(analyzer, sample_products):
    result = analyzer.analyze(sample_products)

    assert result.total_products == 3
    assert result.platforms == {'github_trending': 1, 'hackernews': 1, 'producthunt': 1}
    assert result.top_products[0]['name'] == 'agent-kit'
    # 未提供分类的产品归入 Uncategorized，而不是空字符串
    assert 'Uncategorized' in result.categories
    assert result.tags['open-source'] == 1


def test_top_category_insight_ignores_uncategorized(analyzer, sample_products):
    result = analyzer.analyze(sample_products)
    category_insight = next(i for i in result.insights if '最热门分类' in i)

    # Uncategorized 数量最多，但它不是一个真实分类
    assert 'Uncategorized' not in category_insight
    assert 'Python' in category_insight or 'Show HN' in category_insight


def test_analyze_groups_highlights_per_platform(analyzer, sample_products):
    result = analyzer.analyze(sample_products)

    assert set(result.platform_highlights) == {'github_trending', 'hackernews', 'producthunt'}
    # 没有票数的平台也应出现在各自榜单中
    assert result.platform_highlights['producthunt'][0]['name'] == 'Deploy bot'


def test_analyze_detects_configured_keywords(analyzer, sample_products):
    result = analyzer.analyze(sample_products)
    trends = {t['keyword']: t for t in result.trends}

    assert trends['AI']['count'] == 1
    assert trends['automation']['percentage'] == 33.3


def test_auto_keywords_exclude_stopwords_and_singletons(analyzer, sample_products):
    result = analyzer.analyze(sample_products)

    assert 'the' not in result.auto_keywords
    assert 'a' not in result.auto_keywords
    # 只出现一次的词没有趋势意义，应被过滤
    assert all(count > 1 for count in result.auto_keywords.values())


def test_analyze_without_history_flags_first_run(analyzer, sample_products):
    result = analyzer.analyze(sample_products)

    assert result.history['available'] is False
    assert result.history['new_count'] == 3
    assert any('首次运行' in insight for insight in result.insights)


def test_analyze_with_history_identifies_new_products(analyzer, sample_products):
    history = [sample_products[0]]

    result = analyzer.analyze(sample_products, history=history)

    assert result.history['available'] is True
    assert result.history['new_count'] == 2
    assert result.history['returning_count'] == 1
    new_names = {p['name'] for p in result.history['new_products']}
    assert new_names == {'Notes app', 'Deploy bot'}


def test_keyword_movers_report_direction(analyzer, sample_products):
    # 历史里全是 AI 产品，本次占比下降
    history = [
        {'id': 'x', 'name': 'AI thing', 'description': 'AI', 'platform': 'hackernews'},
        {'id': 'y', 'name': 'AI other', 'description': 'AI', 'platform': 'hackernews'},
    ]

    result = analyzer.analyze(sample_products, history=history)
    movers = {m['keyword']: m for m in result.history['keyword_movers']}

    assert movers['AI']['delta'] < 0
    assert movers['automation']['delta'] > 0


def test_analyze_empty_input_returns_warning(analyzer):
    result = analyzer.analyze([])

    assert result.total_products == 0
    assert result.platforms == {}
    assert '没有数据可分析' in result.insights[0]


# --------------------------------------------------------------- 赛道分类

@pytest.mark.parametrize('name,description,expected', [
    ('claude-mem', 'Persistent context for every agent', 'ai_agent'),
    ('OpenCut', 'The open-source CapCut alternative', 'oss_alt'),
    ('freellmapi', '34 free LLM providers and 635 model endpoints', 'llm'),
    ('JobGlance', 'Rank every visa and remote job by your resume fit', 'career'),
    ('open-seo', 'Open source alternative to Semrush and Ahrefs', 'oss_alt'),
    ('Vaultly', 'Zero-knowledge encryption for your passwords', 'security'),
    # "from scratch" 描述的是形式而非领域，不该盖过 LLM 这样的领域词
    ('minimind', 'Train a 64M-parameter LLM from scratch in just 2h', 'llm'),
])
def test_classify_assigns_expected_theme(name, description, expected):
    primary, matched = classify(name, description)

    assert primary == expected
    assert expected in matched


def test_classify_falls_back_to_other():
    primary, matched = classify('Zzz', 'qqq wwww')

    assert primary == 'other'
    assert matched == ['other']


def test_classify_returns_all_matched_themes():
    # 一个产品可以同时属于多个赛道，便于按任一赛道筛选
    _, matched = classify('AgentDeploy', 'Deploy your AI agent to kubernetes')

    assert 'ai_agent' in matched
    assert 'infra' in matched


def test_theme_label_is_human_readable():
    assert theme_label('ai_agent') == 'AI 智能体'
    assert theme_label('unknown_key') == 'unknown_key'


# ------------------------------------------------------- 热度归一化（跨平台可比）

@pytest.fixture
def mixed_scale_products():
    """GitHub 星数量级远大于 HN 票数，用于验证归一化"""
    products = []
    for i, stars in enumerate([20000, 5000, 800]):
        products.append({
            'id': f'gh_{i}', 'name': f'repo-{i}', 'description': 'a developer cli tool',
            'url': f'https://github.com/x/repo-{i}', 'platform': 'github_trending',
            'votes': stars, 'comments': 0, 'category': 'Python', 'tags': [],
        })
    for i, points in enumerate([47, 20, 3]):
        products.append({
            'id': f'hn_{i}', 'name': f'show-{i}', 'description': 'a productivity notes app',
            'url': f'https://hn.example/{i}', 'platform': 'hackernews',
            'votes': points, 'comments': 2, 'category': 'Show HN', 'tags': [],
        })
    for i in range(3):
        products.append({
            'id': f'ph_{i}', 'name': f'launch-{i}', 'description': 'an ai agent for design',
            'url': f'https://producthunt.example/{i}', 'platform': 'producthunt',
            'votes': 0, 'comments': 0, 'category': '', 'tags': [],
        })
    return products


def test_top_products_are_not_monopolized_by_high_scale_platform(analyzer, mixed_scale_products):
    result = analyzer.analyze(mixed_scale_products)
    top_platforms = {p['platform'] for p in result.top_products[:3]}

    # 归一化前 GitHub 的量级会垄断榜首；归一化后各平台的头部应同时出现
    assert len(top_platforms) > 1
    assert 'hackernews' in top_platforms


def test_heat_is_percentile_within_platform(analyzer, mixed_scale_products):
    result = analyzer.analyze(mixed_scale_products)
    by_id = {p['id']: p for p in result.products}

    # 各平台内部的头名都应拿到最高分，与绝对量级无关
    assert by_id['gh_0']['heat'] == by_id['hn_0']['heat']
    assert by_id['gh_0']['heat'] > by_id['gh_1']['heat'] > by_id['gh_2']['heat']
    assert by_id['hn_0']['heat'] > by_id['hn_2']['heat']


def test_platforms_without_votes_are_flagged(analyzer, mixed_scale_products):
    result = analyzer.analyze(mixed_scale_products)
    by_id = {p['id']: p for p in result.products}

    assert by_id['hn_0']['has_real_heat'] is True
    # Product Hunt feed 没有票数，热度分只是列表顺序的折算，需要标记出来
    assert by_id['ph_0']['has_real_heat'] is False
    assert '无公开热度数据' in result.platform_meta['producthunt']['heat_basis']
    assert result.platform_meta['hackernews']['heat_basis'] == '得票数'


def test_equal_signals_get_equal_heat(analyzer):
    products = [
        {'id': f'hn_{i}', 'name': f'p{i}', 'description': 'x', 'url': 'https://x',
         'platform': 'hackernews', 'votes': 10, 'comments': 0, 'category': '', 'tags': []}
        for i in range(4)
    ]

    result = analyzer.analyze(products)
    heats = {p['heat'] for p in result.products}

    # 票数相同的产品不应因排列顺序而分出高下
    assert len(heats) == 1


# ------------------------------------------------------------- 赛道动量与信号

def test_themes_are_aggregated_and_sorted_by_count(analyzer, mixed_scale_products):
    result = analyzer.analyze(mixed_scale_products)
    counts = [t['count'] for t in result.themes]

    assert counts == sorted(counts, reverse=True)
    assert all('label' in t and 'share' in t for t in result.themes)


def test_theme_momentum_is_computed_against_history(analyzer):
    history = [
        {'id': f'h{i}', 'name': f'old-{i}', 'description': 'a productivity notes app',
         'platform': 'hackernews', 'votes': 1, 'tags': []}
        for i in range(8)
    ]
    current = [
        {'id': f'c{i}', 'name': f'new-{i}', 'description': 'an ai agent that writes code',
         'url': 'https://x', 'platform': 'hackernews', 'votes': 5, 'comments': 0,
         'category': '', 'tags': []}
        for i in range(8)
    ]

    result = analyzer.analyze(current, history=history)
    themes = {t['key']: t for t in result.themes}

    # 智能体赛道从 0% 涨到 100%，生产力赛道跌出
    assert themes['ai_agent']['delta'] > 0
    assert themes['ai_agent']['previous_share'] == 0.0


def test_theme_delta_is_none_without_history(analyzer, mixed_scale_products):
    result = analyzer.analyze(mixed_scale_products)

    assert all(t['delta'] is None for t in result.themes)
    assert all(t['previous_share'] is None for t in result.themes)


def test_signals_report_rising_theme(analyzer):
    history = [
        {'id': f'h{i}', 'name': f'old-{i}', 'description': 'a design video editor',
         'platform': 'hackernews', 'votes': 1, 'tags': []}
        for i in range(10)
    ]
    current = [
        {'id': f'c{i}', 'name': f'agentic-{i}', 'description': 'an autonomous ai agent',
         'url': 'https://x', 'platform': 'hackernews', 'votes': 10, 'comments': 0,
         'category': '', 'tags': []}
        for i in range(10)
    ]

    result = analyzer.analyze(current, history=history)
    rising = [s for s in result.signals if s['direction'] == 'up' and s['kind'] == 'momentum']

    assert rising, f"expected a rising momentum signal, got {result.signals}"
    assert rising[0]['theme'] == 'ai_agent'
    assert rising[0]['evidence']


def test_signals_highlight_cross_platform_products(analyzer):
    products = [{
        'id': 'hn_1', 'name': 'Floe', 'description': 'an open source audio plugin',
        'url': 'https://floe.audio', 'platform': 'hackernews', 'votes': 19,
        'comments': 4, 'category': 'Show HN', 'tags': [],
        'metadata': {'also_on': ['producthunt']},
    }]

    result = analyzer.analyze(products)
    kinds = {s['kind'] for s in result.signals}

    assert 'cross_platform' in kinds
    assert any(p['also_on'] == ['producthunt'] for p in result.products)


def test_signals_fall_back_to_leader_on_first_run(analyzer, mixed_scale_products):
    result = analyzer.analyze(mixed_scale_products)

    assert result.signals
    assert result.signals[0]['kind'] == 'leader'
    assert '历史数据' in result.signals[0]['detail']


def test_signals_do_not_repeat_the_same_theme(analyzer):
    """同一赛道的升温与新品集中是同一件事，不该占两张卡"""
    history = [
        {'id': f'h{i}', 'name': f'old-{i}', 'description': 'a design video editor',
         'platform': 'hackernews', 'votes': 1, 'tags': []}
        for i in range(10)
    ]
    current = [
        {'id': f'c{i}', 'name': f'agentic-{i}', 'description': 'an autonomous ai agent',
         'url': 'https://x', 'platform': 'hackernews', 'votes': 10, 'comments': 0,
         'category': '', 'tags': []}
        for i in range(10)
    ]

    result = analyzer.analyze(current, history=history)
    themes = [s['theme'] for s in result.signals if s['theme']]

    assert len(themes) == len(set(themes))


def test_other_theme_never_produces_a_signal(analyzer):
    """"其他"是分类兜底桶，它的涨跌只反映分类覆盖度"""
    history = [
        {'id': f'h{i}', 'name': f'old-{i}', 'description': 'an ai agent', 'platform': 'hackernews',
         'votes': 1, 'tags': []}
        for i in range(10)
    ]
    current = [
        {'id': f'c{i}', 'name': f'zzz-{i}', 'description': 'qqq wwww', 'url': 'https://x',
         'platform': 'hackernews', 'votes': 3, 'comments': 0, 'category': '', 'tags': []}
        for i in range(10)
    ]

    result = analyzer.analyze(current, history=history)

    assert all(s['theme'] != 'other' for s in result.signals)


def test_new_products_are_flagged_in_explorer_rows(analyzer):
    history = [{'id': 'old', 'name': 'Old thing', 'description': 'x', 'platform': 'hackernews'}]
    current = [
        {'id': 'old', 'name': 'Old thing', 'description': 'x', 'url': 'https://a',
         'platform': 'hackernews', 'votes': 5, 'comments': 0, 'category': '', 'tags': []},
        {'id': 'fresh', 'name': 'Fresh thing', 'description': 'y', 'url': 'https://b',
         'platform': 'hackernews', 'votes': 9, 'comments': 0, 'category': '', 'tags': []},
    ]

    result = analyzer.analyze(current, history=history)
    flags = {p['id']: p['is_new'] for p in result.products}

    assert flags == {'old': False, 'fresh': True}


def test_is_new_is_not_guessed_without_history(analyzer, mixed_scale_products):
    result = analyzer.analyze(mixed_scale_products)

    # 没有历史数据时无法判断新旧，不应把所有产品都标成新品
    assert all(p['is_new'] is False for p in result.products)


# --------------------------------------------------------------- 单品动量

@pytest.fixture
def returning_products():
    return [
        {'id': 'hn_up', 'name': 'Rising tool', 'description': 'a developer cli',
         'url': 'https://a', 'platform': 'hackernews', 'votes': 90, 'comments': 3,
         'category': '', 'tags': []},
        {'id': 'hn_down', 'name': 'Fading tool', 'description': 'a developer cli',
         'url': 'https://b', 'platform': 'hackernews', 'votes': 20, 'comments': 1,
         'category': '', 'tags': []},
        {'id': 'ph_x', 'name': 'Feed product', 'description': 'a saas dashboard',
         'url': 'https://c', 'platform': 'producthunt', 'votes': 0, 'comments': 0,
         'category': '', 'tags': []},
    ]


def _stats(**kwargs):
    return {
        key: {'prev_votes': prev, 'first_seen': '2026-09-01T10:00:00', 'appearances': 3}
        for key, prev in kwargs.items()
    }


def test_votes_delta_is_computed_against_previous_snapshot(analyzer, returning_products):
    result = analyzer.analyze(
        returning_products,
        history=[{'id': 'hn_up'}, {'id': 'hn_down'}, {'id': 'ph_x'}],
        product_stats=_stats(hn_up=30, hn_down=25),
    )
    deltas = {p['id']: p['votes_delta'] for p in result.products}

    assert deltas['hn_up'] == 60
    assert deltas['hn_down'] == -5


def test_platforms_without_real_votes_get_no_fabricated_momentum(analyzer, returning_products):
    """PH feed 的位次波动不代表热度变化，不能拿来编造动量"""
    result = analyzer.analyze(
        returning_products,
        history=[{'id': 'ph_x'}],
        product_stats=_stats(ph_x=0),
    )
    row = next(p for p in result.products if p['id'] == 'ph_x')

    assert row['votes_delta'] is None
    assert row['appearances'] == 3


def test_delta_is_none_for_first_time_products(analyzer, returning_products):
    result = analyzer.analyze(
        returning_products,
        history=[{'id': 'hn_up'}],
        product_stats=_stats(hn_up=30),
    )
    fresh = next(p for p in result.products if p['id'] == 'hn_down')

    assert fresh['votes_delta'] is None
    assert fresh['appearances'] == 0


def test_surge_signal_reports_accelerating_products(analyzer, returning_products):
    result = analyzer.analyze(
        returning_products,
        history=[{'id': 'hn_up'}, {'id': 'hn_down'}],
        product_stats=_stats(hn_up=30, hn_down=25),
    )
    surge = next((s for s in result.signals if s['kind'] == 'surge'), None)

    assert surge is not None
    assert [item['name'] for item in surge['evidence']] == ['Rising tool']
    assert '+60' in surge['evidence'][0]['note']


def test_surge_signal_ignores_small_absolute_gains(analyzer):
    """1 票涨到 3 票是 200%，但没有信息量"""
    products = [
        {'id': 'tiny', 'name': 'Tiny', 'description': 'a cli', 'url': 'https://a',
         'platform': 'hackernews', 'votes': 3, 'comments': 0, 'category': '', 'tags': []},
    ]

    result = analyzer.analyze(
        products, history=[{'id': 'tiny'}], product_stats=_stats(tiny=1)
    )

    assert not any(s['kind'] == 'surge' for s in result.signals)


def test_surge_ranks_by_relative_growth_not_absolute(analyzer):
    """+6000 星（30%）不如 20 票涨到 80（300%）说明问题"""
    products = [
        {'id': 'gh_big', 'name': 'Big repo', 'description': 'a cli', 'url': 'https://a',
         'platform': 'github_trending', 'votes': 26000, 'comments': 0,
         'category': '', 'tags': []},
        {'id': 'gh_small', 'name': 'Small repo', 'description': 'a cli', 'url': 'https://b',
         'platform': 'github_trending', 'votes': 80, 'comments': 0,
         'category': '', 'tags': []},
    ]

    result = analyzer.analyze(
        products,
        history=[{'id': 'gh_big'}, {'id': 'gh_small'}],
        product_stats=_stats(gh_big=20000, gh_small=20),
    )
    surge = next(s for s in result.signals if s['kind'] == 'surge')

    assert [item['name'] for item in surge['evidence']] == ['Small repo', 'Big repo']


def test_surge_ignores_low_relative_growth_on_large_bases(analyzer):
    """两万星涨 500 属于正常增速，不该被当成加速上涨"""
    products = [
        {'id': 'gh_big', 'name': 'Big repo', 'description': 'a cli', 'url': 'https://a',
         'platform': 'github_trending', 'votes': 20500, 'comments': 0,
         'category': '', 'tags': []},
    ]

    result = analyzer.analyze(
        products, history=[{'id': 'gh_big'}], product_stats=_stats(gh_big=20000)
    )

    assert not any(s['kind'] == 'surge' for s in result.signals)


def test_dashboard_exposes_momentum_column_and_filter(tmp_path, analyzer, returning_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(
        returning_products,
        history=[{'id': 'hn_up'}, {'id': 'hn_down'}],
        product_stats=_stats(hn_up=30, hn_down=25),
    )
    html = open(generator.generate(result, 'html'), encoding='utf-8').read()

    assert 'data-sort="votes_delta"' in html
    assert 'data-quick="surge"' in html
    assert '"votes_delta":60' in html


def test_markdown_surfaces_growth_next_to_evidence(tmp_path, analyzer, returning_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(
        returning_products,
        history=[{'id': 'hn_up'}, {'id': 'hn_down'}],
        product_stats=_stats(hn_up=30, hn_down=25),
    )
    md = open(generator.generate(result, 'markdown'), encoding='utf-8').read()

    assert '+60' in md


# ------------------------------------------------------------------- 报告

def test_report_generator_writes_all_formats(tmp_path, analyzer, sample_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(sample_products)

    for fmt in ('html', 'json', 'markdown'):
        path = generator.generate(result, fmt)
        assert path.startswith(str(tmp_path))

    assert len(list(tmp_path.glob('report_*'))) == 3


def test_json_report_is_machine_readable(tmp_path, analyzer, sample_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(sample_products)

    payload = json.loads(open(generator.generate(result, 'json'), encoding='utf-8').read())

    assert payload['total_products'] == 3
    assert payload['platforms']['github_trending'] == 1
    assert 'platform_highlights' in payload


def test_html_report_escapes_product_names(tmp_path, analyzer):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze([{
        'id': 'x', 'name': '<script>alert(1)</script>', 'description': 'a & b',
        'url': 'https://x.example/"onload="alert(1)', 'platform': 'hackernews',
        'votes': 5, 'comments': 0, 'category': 'Show HN', 'tags': [],
    }])

    html = open(generator.generate(result, 'html'), encoding='utf-8').read()

    assert '<script>alert(1)</script>' not in html
    # 产品名现在走内联 JSON 交给前端渲染，尖括号应以 unicode 转义形式存在
    assert '\\u003cscript\\u003e' in html
    assert '"onload="' not in html


def test_html_report_uses_display_platform_names(tmp_path, analyzer, sample_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(sample_products)

    html = open(generator.generate(result, 'html'), encoding='utf-8').read()

    assert 'GitHub Trending' in html
    assert 'Hacker News' in html


def test_markdown_report_escapes_table_pipes(tmp_path, analyzer):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze([{
        'id': 'x', 'name': 'A | B', 'description': 'x | y', 'url': 'https://x.example',
        'platform': 'hackernews', 'votes': 1, 'comments': 0, 'category': '', 'tags': [],
    }])

    markdown = open(generator.generate(result, 'markdown'), encoding='utf-8').read()

    assert 'A \\| B' in markdown


def test_html_dashboard_embeds_all_products_as_json(tmp_path, analyzer, mixed_scale_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(mixed_scale_products)

    html = open(generator.generate(result, 'html'), encoding='utf-8').read()
    payload = html.split('id="product-data">')[1].split('</script>')[0]
    products = json.loads(payload.replace('\\u003c', '<').replace('\\u003e', '>')
                          .replace('\\u0026', '&'))

    # 明细表由前端渲染，所有产品都要进 JSON，否则搜索筛选会漏数据
    assert len(products) == len(mixed_scale_products)
    assert {'heat', 'theme', 'is_new', 'platform_label'} <= set(products[0])


def test_html_dashboard_has_decision_sections_in_order(tmp_path, analyzer, mixed_scale_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(mixed_scale_products)

    html = open(generator.generate(result, 'html'), encoding='utf-8').read()

    # 结论 → 赛道 → 明细，先看结论再下钻
    assert html.index('id="signals"') < html.index('id="themes"') < html.index('id="explorer"')
    assert '本次结论' in html and '赛道热力' in html and '产品明细' in html


def test_html_dashboard_includes_interactive_controls(tmp_path, analyzer, mixed_scale_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(mixed_scale_products)

    html = open(generator.generate(result, 'html'), encoding='utf-8').read()

    assert 'id="q"' in html                        # 搜索框
    assert 'data-sort="heat"' in html              # 可排序列头
    assert 'data-platform="hackernews"' in html    # 平台筛选
    assert 'data-theme=' in html                   # 赛道筛选


def test_html_dashboard_explains_heat_basis(tmp_path, analyzer, mixed_scale_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(mixed_scale_products)

    html = open(generator.generate(result, 'html'), encoding='utf-8').read()

    # 热度分是归一化结果，必须说明口径，否则会被误读为原始票数
    assert '平台内百分位' in html
    assert '得票数' in html


def test_html_dashboard_escapes_injected_payload(tmp_path, analyzer):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze([{
        'id': 'x', 'name': '</script><script>alert(1)</script>',
        'description': 'a & b', 'url': 'https://x.example/"onload="alert(1)',
        'platform': 'hackernews', 'votes': 5, 'comments': 0, 'category': '', 'tags': [],
    }])

    html = open(generator.generate(result, 'html'), encoding='utf-8').read()

    # 内联 JSON 里的尖括号必须转义，否则会提前闭合 script 标签
    assert '</script><script>alert(1)</script>' not in html
    assert '"onload="' not in html
    assert html.count('id="product-data"') == 1


def test_markdown_report_leads_with_conclusions(tmp_path, analyzer, mixed_scale_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(mixed_scale_products)

    markdown = open(generator.generate(result, 'markdown'), encoding='utf-8').read()

    assert markdown.index('## 本次结论') < markdown.index('## 赛道热力')
    assert markdown.index('## 赛道热力') < markdown.index('## 值得看的产品')


def test_report_generator_rejects_unknown_format(tmp_path, analyzer, sample_products):
    generator = ReportGenerator({'reports_dir': str(tmp_path)})
    result = analyzer.analyze(sample_products)

    with pytest.raises(ValueError, match='Unsupported format'):
        generator.generate(result, 'pdf')


# ------------------------------------------------------------------- 调度

def test_cron_matches_daily_time():
    cron = CronExpression('0 9 * * *')

    assert cron.matches(datetime(2026, 9, 1, 9, 0))
    assert not cron.matches(datetime(2026, 9, 1, 9, 1))
    assert not cron.matches(datetime(2026, 9, 1, 8, 0))


def test_cron_next_after_rolls_to_next_day():
    cron = CronExpression('0 9 * * *')

    assert cron.next_after(datetime(2026, 9, 1, 9, 0)) == datetime(2026, 9, 2, 9, 0)
    assert cron.next_after(datetime(2026, 9, 1, 8, 30)) == datetime(2026, 9, 1, 9, 0)


def test_cron_supports_steps_lists_and_ranges():
    assert CronExpression('*/15 * * * *').matches(datetime(2026, 9, 1, 3, 30))
    assert not CronExpression('*/15 * * * *').matches(datetime(2026, 9, 1, 3, 31))
    assert CronExpression('0 9,18 * * *').matches(datetime(2026, 9, 1, 18, 0))
    assert CronExpression('0 9 * * 1-5').matches(datetime(2026, 9, 1, 9, 0))  # 周二


def test_cron_weekday_sunday_is_zero():
    cron = CronExpression('30 8 * * 0')

    assert cron.matches(datetime(2026, 9, 6, 8, 30))   # 周日
    assert not cron.matches(datetime(2026, 9, 7, 8, 30))  # 周一


@pytest.mark.parametrize('expression', [
    '0 9 * *',          # 字段不足
    '0 25 * * *',       # 小时越界
    '99 * * * *',       # 分钟越界
    '0 9 * * 1-9',      # 星期越界
    '*/0 * * * *',      # 步长非法
])
def test_cron_rejects_invalid_expressions(expression):
    with pytest.raises(ValueError):
        CronExpression(expression)


def test_scheduler_uses_interval_by_default():
    scheduler = Scheduler({'interval_minutes': 60, 'cron_expression': '0 9 * * *'})

    # use_cron 未开启时应忽略 cron_expression
    assert scheduler.cron is None
    assert scheduler.mode == 'every 60min'
    assert scheduler._compute_next_run(datetime(2026, 9, 1, 10, 0)) == datetime(2026, 9, 1, 11, 0)


def test_scheduler_uses_cron_when_enabled():
    scheduler = Scheduler({'use_cron': True, 'cron_expression': '30 7 * * *'})

    assert scheduler.mode == "cron(30 7 * * *)"
    assert scheduler._compute_next_run(datetime(2026, 9, 1, 10, 0)) == datetime(2026, 9, 2, 7, 30)


def test_scheduler_falls_back_to_interval_on_bad_cron():
    scheduler = Scheduler({
        'use_cron': True, 'cron_expression': 'not a cron', 'interval_minutes': 15,
    })

    # 配置写错不应导致启动失败，而是退回间隔模式
    assert scheduler.cron is None
    assert scheduler.mode == 'every 15min'


def test_scheduler_status_reports_mode():
    scheduler = Scheduler({'use_cron': True, 'cron_expression': '0 9 * * *'})
    status = scheduler.get_status()

    assert status['running'] is False
    assert status['cron_expression'] == '0 9 * * *'
    assert status['run_count'] == 0
