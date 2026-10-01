"""
新平台采集器的离线单元测试

全部不联网：用内联 HTML / RSS / Next.js 负载样本驱动解析路径，
覆盖新增的 5 个可用平台与 3 个受限平台的降级行为。
"""

import json
from xml.etree import ElementTree

import pytest
from bs4 import BeautifulSoup

from collectors import get_collector
from collectors.base import CollectorError
from collectors.betabound import BetaBoundCollector
from collectors.blocked import WafBlockedCollector
from collectors.devhunt import DevHuntCollector
from collectors.fazier import FazierCollector
from collectors.indiehackers import IndieHackersCollector
from collectors.microlaunch import MicroLaunchCollector
from collectors.peerlist import PeerlistCollector
from collectors.rss import parse_feed
from collectors.startupage import StartuPageCollector
from collectors.uneed import UneedCollector
from collectors.xinquji import XinqujiCollector


def _offline(collector, html):
    """把采集器的网络取数替换成固定页面"""
    collector._make_request = lambda url, headers=None: html
    return collector


def _next_data(payload) -> str:
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + '</script></head><body></body></html>'
    )


# --------------------------------------------------------------- Fazier

FAZIER_PAYLOAD = {
    'props': {
        'pageProps': {
            'posts': [
                {
                    'date': '2026-10-01',
                    'posts': [
                        {
                            'id': 1, 'slug': 'readytopost-2', 'name': 'ReadyToPost',
                            'tagline': 'The AI community manager that posts for you',
                            'thumbnail_link': 'https://img/1.png',
                            'launch_date': '2026-10-01', 'pricing_type': 'Freemium',
                            'category_type': 'Marketing', 'upvotes_count': 10,
                            'comments_count': 3, 'is_published': True,
                        },
                        {
                            'id': 2, 'slug': 'biz-tray', 'name': 'Biz Tray',
                            'tagline': 'Document utility belt',
                            'upvotes_count': 9, 'comments_count': 0,
                            'pricing_type': 'Paid', 'category_type': 'Productivity',
                        },
                    ],
                }
            ],
            'weeklyPosts': [
                {
                    'date': '2026-W40',
                    'posts': [
                        # 同一产品也上了周榜，票数更低，应被日榜那条替换掉
                        {'id': 1, 'slug': 'readytopost-2', 'name': 'ReadyToPost',
                         'tagline': 'The AI community manager', 'upvotes_count': 4},
                    ],
                }
            ],
            # 广告位混在同一个 pageProps 里，必须排除
            'premiumAds': [{'id': 900, 'name': 'Buy This Ad', 'tagline': 'spam',
                            'ad_type': 'premium'}],
        }
    }
}


def test_fazier_reads_next_data_and_keeps_votes():
    collector = _offline(FazierCollector({'name': 'Fazier'}), _next_data(FAZIER_PAYLOAD))
    products = collector.collect()

    assert len(products) == 2
    first = products[0]
    assert first.id == 'fz_readytopost-2'
    assert first.name == 'ReadyToPost'
    assert first.votes == 10
    assert first.comments == 3
    assert first.url == 'https://fazier.com/launches/readytopost-2'
    assert first.category == 'Marketing'


def test_fazier_excludes_inline_ads():
    collector = _offline(FazierCollector({'name': 'Fazier'}), _next_data(FAZIER_PAYLOAD))
    names = [p.name for p in collector.collect()]

    # premiumAds 不是自然榜单，混进来会污染赛道统计
    assert 'Buy This Ad' not in names


def test_fazier_keeps_the_higher_vote_duplicate():
    collector = _offline(FazierCollector({'name': 'Fazier'}), _next_data(FAZIER_PAYLOAD))
    same = [p for p in collector.collect() if p.id == 'fz_readytopost-2']

    assert len(same) == 1
    assert same[0].votes == 10  # 日榜的 10 票，而不是周榜的 4 票


FAZIER_HTML = """
<div class="card">
  <a href="/launches/cool-dock">
    <div class="launch-title">CoolDock</div>
    <div class="launch-tagline">A dock replacement for macOS</div>
  </a>
</div>
"""


def test_fazier_falls_back_to_html_cards():
    collector = _offline(FazierCollector({'name': 'Fazier'}), FAZIER_HTML)
    products = collector.collect()

    assert len(products) == 1
    assert products[0].name == 'CoolDock'
    assert products[0].description == 'A dock replacement for macOS'
    assert products[0].votes == 0  # HTML 回退拿不到票数


# --------------------------------------------------------------- DevHunt

DEVHUNT_TOOL = {
    'id': 6129,
    'slug': 'mcpindex',
    'name': 'MCPIndex',
    'slogan': 'Let your LLM find the right tool automatically',
    'description': 'A Model Context Protocol server for tool discovery.',
    'logo_url': 'https://img/mcp.png',
    'demo_url': 'https://npmjs.com/pkg',
    'launch_date': '2026-09-29',
    'week': 39,
    'views_count': 1289,
    'votes_count': 3,
    'product_pricing_types': {'title': 'Free'},
    # 嵌套对象：括号配对必须能正确跳过它
    'product_categories': [{'id': 14, 'name': 'MCP'}],
}


def _flight_script(blob: str) -> str:
    return (
        '<html><body><script>self.__next_f.push([1,'
        + json.dumps(blob)
        + '])</script></body></html>'
    )


def test_devhunt_reads_flight_payload_including_nested_objects():
    html = _flight_script(json.dumps([DEVHUNT_TOOL]))
    objects = list(DevHuntCollector._iter_flight_objects(html))

    assert len(objects) == 1
    assert objects[0]['slug'] == 'mcpindex'
    # 嵌套的 product_categories 不能被当成独立产品再吐出来
    assert objects[0]['product_categories'] == [{'id': 14, 'name': 'MCP'}]


def test_devhunt_product_fields_from_flight():
    collector = _offline(DevHuntCollector({'name': 'DevHunt'}),
                         _flight_script(json.dumps([DEVHUNT_TOOL])))
    products = collector.collect()

    assert len(products) == 1
    product = products[0]
    assert product.id == 'dh_mcpindex'
    assert product.votes == 3
    assert product.category == 'MCP'
    assert product.url == 'https://devhunt.org/tool/mcpindex'
    assert product.metadata['views'] == 1289
    assert product.metadata['pricing'] == 'Free'
    assert 'mcp' in product.tags


DEVHUNT_HTML = """
<ul>
  <li>
    <div class="flex w-full min-w-0 items-center gap-x-4">
      <a class="flex-none" href="/tool/hyperfrontend"><img alt="Hyperfrontend" src="https://img/hf.png"/></a>
      <div class="w-full min-w-0 space-y-1">
        <h3><span class="min-w-0 truncate">Hyperfrontend</span></h3>
        <a href="/tool/hyperfrontend"><p class="text-slate-400">Frontend freedom, without the rewrite.</p></a>
      </div>
    </div>
  </li>
  <li>
    <div class="group relative">
      <a href="/tool/devutilx"><span class="font-medium text-slate-100">DevUtilX</span><span class="text-slate-500"> · 100+ free developer tools</span></a>
    </div>
  </li>
  <li><a href="/tools/ai">AI</a></li>
</ul>
"""


def test_devhunt_html_fallback_handles_both_card_layouts():
    collector = DevHuntCollector({'name': 'DevHunt'})
    products = collector._collect_from_html(DEVHUNT_HTML, '/')
    by_slug = {p.metadata['slug']: p for p in products}

    assert set(by_slug) == {'hyperfrontend', 'devutilx'}
    assert by_slug['hyperfrontend'].name == 'Hyperfrontend'
    assert by_slug['hyperfrontend'].description == 'Frontend freedom, without the rewrite.'
    # 另一套布局把名称和简介都放在链接内，用 · 分隔
    assert by_slug['devutilx'].name == 'DevUtilX'
    assert by_slug['devutilx'].description == '100+ free developer tools'


def test_devhunt_ignores_category_pages():
    collector = DevHuntCollector({'name': 'DevHunt'})
    products = collector._collect_from_html(DEVHUNT_HTML, '/')

    # 复数 /tools/<category> 是分类页，不是产品
    assert 'ai' not in {p.metadata['slug'] for p in products}


def test_devhunt_raises_when_every_page_is_an_error_page():
    collector = _offline(DevHuntCollector({'name': 'DevHunt'}),
                         '<div id="__next_error__"></div>')

    with pytest.raises(CollectorError):
        collector.collect()


# --------------------------------------------------------------- Indie Hackers

INDIEHACKERS_HTML = """
<div class="product-card">
  <a class="product-card__link" href="/product/limereach-2">
    <div class="product-card__header">
      <picture class="product-card__logo"><img src="https://img/lr.webp"/></picture>
      <div class="product-card__header-text">
        <span class="product-card__name">Limereach</span>
        <span class="product-card__tagline">Startup launch board for driven founders</span>
      </div>
    </div>
    <div class="product-card__revenue">
      <div class="product-card__revenue-text">
        <span class="product-card__revenue-number">$92,000<span>/</span><span>month</span></span>
      </div>
    </div>
  </a>
</div>
<div class="product-card">
  <a class="product-card__link" href="/product/day-wheel">
    <div class="product-card__header-text">
      <span class="product-card__name">Day Wheel</span>
      <span class="product-card__tagline">Day controlling app</span>
    </div>
    <div class="product-card__revenue">
      <span class="product-card__revenue-number">$0<span>/</span><span>month</span></span>
    </div>
  </a>
</div>
"""


def test_indiehackers_parses_card_and_mrr():
    collector = IndieHackersCollector({'name': 'Indie Hackers'})
    cards = BeautifulSoup(INDIEHACKERS_HTML, 'html.parser').select('.product-card')
    products = [collector._parse_card(card) for card in cards]

    assert len(products) == 2
    first, second = products
    assert first.id == 'ih_limereach-2'
    assert first.name == 'Limereach'
    assert first.votes == 92000  # MRR 作为热度口径
    assert first.description == 'Startup launch board for driven founders'
    assert first.url == 'https://www.indiehackers.com/product/limereach-2'
    # $0 也要能解析成 0，而不是解析失败
    assert second.votes == 0


@pytest.mark.parametrize('text,expected', [
    ('$0 / month', 0),
    ('$92,000 / month', 92000),
    ('$12k / month', 12000),
    ('$1.5M / month', 1500000),
    ('no numbers here', 0),
    ('', 0),
])
def test_indiehackers_money_parsing(text, expected):
    assert IndieHackersCollector._parse_money(text) == expected


# --------------------------------------------------------------- 新趣集 (RSS)

XINQUJI_RSS = """<rss version="2.0"><channel><title>新趣集</title>
<item>
  <title><![CDATA[ LaTeX Autofill - Obsidian 公式补全插件 ]]></title>
  <link>https://xinquji.com/posts/859453?utm_campaign=xinquji-rss</link>
  <description><![CDATA[ <p>Obsidian 公式补全插件，离线 MIT</p> ]]></description>
  <pubDate>Wed, 30 Sep 2026 09:50:08 CST</pubDate>
</item>
<item>
  <title></title>
  <link>https://xinquji.com/posts/1</link>
</item>
</channel></rss>"""


def test_xinquji_parses_feed_and_strips_tracking():
    entries = parse_feed(ElementTree.fromstring(XINQUJI_RSS))
    # 缺标题的条目应被丢弃
    assert len(entries) == 1

    collector = XinqujiCollector({'name': '新趣集'})
    product = collector._parse_product(entries[0])

    assert product.id == 'xq_859453'
    assert product.url == 'https://xinquji.com/posts/859453'
    assert product.description == 'Obsidian 公式补全插件，离线 MIT'
    assert product.created_at.startswith('Wed, 30 Sep 2026')
    assert product.platform == 'xinquji'


def test_xinquji_collect_uses_feed(monkeypatch):
    collector = XinqujiCollector({'name': '新趣集'})
    monkeypatch.setattr(
        type(collector), '_make_xml_request',
        lambda self, url, headers=None: ElementTree.fromstring(XINQUJI_RSS),
    )

    products = collector.collect()
    assert len(products) == 1
    assert products[0].id == 'xq_859453'


# --------------------------------------------------------------- Betabound (RSS)

BETABOUND_RSS = """<rss version="2.0"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item>
  <title>Inseego FX5100 Router Private Beta</title>
  <link>https://betabound.com/inseego-fx5100-router-private-beta/</link>
  <dc:creator>Hailey</dc:creator>
  <pubDate>Tue, 29 Sep 2026 18:43:59 +0000</pubDate>
  <category>Opportunity</category>
  <description><![CDATA[<p>A router with 5G performance</p>
  <p>The post <a href="https://betabound.com/x/">Inseego</a> appeared first on <a href="https://betabound.com">Betabound</a>.</p>]]></description>
</item>
</channel></rss>"""


def test_betabound_parses_feed_and_strips_boilerplate():
    entries = parse_feed(ElementTree.fromstring(BETABOUND_RSS))
    assert len(entries) == 1

    collector = BetaBoundCollector({'name': 'Betabound'})
    product = collector._parse_product(entries[0])

    assert product.id == 'bb_inseego-fx5100-router-private-beta'
    assert product.author == 'Hailey'
    assert product.category == 'Opportunity'
    assert product.url == 'https://betabound.com/inseego-fx5100-router-private-beta/'
    # WordPress 会在正文尾部重复一段 "The post ... appeared first on ..."
    assert 'appeared first on' not in product.description
    assert product.description == 'A router with 5G performance'


# --------------------------------------------------------------- StartuPage

STARTUPAGE_HTML = """
<div class="bg-white rounded-md overflow-hidden">
  <div class="border-b border-black last:border-b-0 px-4 py-2">
    <div class="flex items-center gap-3 md:gap-4">
      <a class="w-10 h-10" href="/startups/clawra-ai">
        <img alt="Clawra AI" src="/_next/image?url=https%3A%2F%2Fcdn.example%2Flogo.webp&amp;w=96&amp;q=75"/>
      </a>
      <div class="min-w-0 flex-1 overflow-hidden">
        <a class="font-semibold text-sm truncate block" href="/startups/clawra-ai">Clawra AI</a>
        <p class="text-xs text-base-content/60 truncate">AI companions for chat and roleplay</p>
      </div>
      <div class="hidden md:block w-[180px] shrink-0">hassan</div>
      <div class="text-right shrink-0 w-[60px]"><p class="text-sm font-bold">$69</p></div>
    </div>
  </div>
</div>
"""


def test_startupage_parses_row_and_unwraps_next_image():
    collector = _offline(StartuPageCollector({'name': 'StartuPage'}), STARTUPAGE_HTML)
    products = collector.collect()

    assert len(products) == 1
    product = products[0]
    assert product.id == 'sa_clawra-ai'
    assert product.name == 'Clawra AI'
    assert product.votes == 69  # MRR
    assert product.description == 'AI companions for chat and roleplay'
    assert product.url == 'https://startupa.ge/startups/clawra-ai'
    # Next.js 图片代理把真实地址藏在 url 查询参数里
    assert product.image == 'https://cdn.example/logo.webp'


# --------------------------------------------------------------- 受限平台

def test_uneed_reports_cloudflare_block_instead_of_silent_empty():
    collector = UneedCollector({'name': 'Uneed', '_platform_key': 'uneed'})
    collector._fetch = lambda url, headers=None: None

    with pytest.raises(CollectorError, match='Cloudflare'):
        collector.collect()


def test_microlaunch_reports_cloudflare_block():
    collector = MicroLaunchCollector(
        {'name': 'MicroLaunch', '_platform_key': 'microlaunch'})
    collector._fetch = lambda url, headers=None: None

    with pytest.raises(CollectorError, match='Cloudflare'):
        collector.collect()


def test_peerlist_explains_it_needs_a_headless_browser():
    collector = PeerlistCollector({'name': 'Peerlist Launchpad'})

    with pytest.raises(CollectorError, match='客户端渲染'):
        collector.collect()


BLOCKED_HTML = """
<div class="card">
  <a href="/tool/awesome-thing"><img alt="Awesome Thing" src="https://img/a.png"/></a>
  <h3>Awesome Thing</h3>
  <p>A very useful tool for makers</p>
</div>
"""


def test_blocked_collector_parses_when_site_is_reachable():
    collector = UneedCollector({'name': 'Uneed', '_platform_key': 'uneed'})

    class _Response:
        text = BLOCKED_HTML

    collector._fetch = lambda url, headers=None: _Response()
    products = collector.collect()

    assert len(products) == 1
    assert products[0].id == 'un_awesome-thing'
    assert products[0].platform == 'uneed'
    assert products[0].url == 'https://www.uneed.best/tool/awesome-thing'
    # 解析规则未经验证，明确标出来便于后续排查
    assert products[0].metadata['parser_verified'] is False


def test_blocked_collector_is_a_base_collector():
    assert issubclass(UneedCollector, WafBlockedCollector)
    assert issubclass(MicroLaunchCollector, WafBlockedCollector)


# --------------------------------------------------------------- 注册与平台键

@pytest.mark.parametrize('name', [
    'fazier', 'devhunt', 'indiehackers', 'xinquji', 'betabound',
    'startupage', 'uneed', 'microlaunch', 'peerlist',
])
def test_new_platforms_are_registered(name):
    config = {'name': name, '_platform_key': name}
    assert get_collector(name, config) is not None
