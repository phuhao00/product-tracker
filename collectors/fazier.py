"""
Fazier 数据收集器

Fazier 主打更透明、更真实的反馈，竞争压力小于 Product Hunt，新品更容易在首页拿到曝光。
站点是 Next.js，首页把当日 / 本周 / 本月的三组榜单直接内联在 __NEXT_DATA__ 里，
取 JSON 比解析 HTML 稳定得多，而且带票数与评论数 —— 这是少数能拿到票数的打榜平台。
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, Product

logger = logging.getLogger(__name__)

# 首页内联的三组榜单：当日 / 本周 / 本月，曝光范围依次放宽
FEED_BUCKETS = ('posts', 'weeklyPosts', 'monthlyPosts')
# 广告位混在 pageProps 里，不是自然榜单，必须排除
AD_BUCKETS = ('premiumAds', 'sponsorAds')

LAUNCH_RE = re.compile(r'/launches/([^/?#]+)')
TITLE_SELECTOR = '.launch-title'
TAGLINE_SELECTOR = '.launch-tagline'


class FazierCollector(BaseCollector):
    """Fazier 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://fazier.com').rstrip('/')
        self.periods = config.get('periods', list(FEED_BUCKETS))

    def collect(self) -> List[Product]:
        html = self._make_request(f'{self.base_url}/')
        if not html:
            return []

        products = self._collect_from_next_data(html)
        if not products:
            logger.warning('Fazier __NEXT_DATA__ 不可用，回退到 HTML 卡片解析')
            products = self._collect_from_html(html)

        unique = self._dedupe_keep_best(products)
        logger.info(f'Parsed {len(unique)} unique products from Fazier')
        return unique[:self.max_items]

    # ---------- 首选：Next.js 内联数据 ----------

    def _collect_from_next_data(self, html: str) -> List[Product]:
        page_props = self._read_page_props(html)
        if not page_props:
            return []

        products: List[Product] = []
        for bucket in self.periods:
            for group in page_props.get(bucket) or []:
                # posts 是 [{date, posts: [...]}, ...]，weeklyPosts / monthlyPosts 同构
                items = group.get('posts') if isinstance(group, dict) else group
                for item in items or []:
                    product = self._parse_product(item)
                    if product:
                        product.metadata['bucket'] = bucket
                        products.append(product)
        return products

    @staticmethod
    def _read_page_props(html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, 'html.parser')
        tag = soup.find('script', id='__NEXT_DATA__')
        if not tag or not tag.string:
            return {}
        try:
            payload = json.loads(tag.string)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f'Fazier __NEXT_DATA__ 解析失败: {e}')
            return {}
        return (payload.get('props') or {}).get('pageProps') or {}

    # ---------- 回退：HTML 卡片 ----------

    def _collect_from_html(self, html: str) -> List[Product]:
        """站点改版或 __NEXT_DATA__ 被移除时，按卡片类名兜底（无票数）"""
        soup = BeautifulSoup(html, 'html.parser')
        buckets: Dict[str, Dict[str, str]] = {}

        for link in soup.find_all('a', href=LAUNCH_RE):
            match = LAUNCH_RE.search(link.get('href', ''))
            if not match:
                continue
            slug = match.group(1)
            bucket = buckets.setdefault(slug, {'name': '', 'tagline': '', 'image': ''})
            card = self._find_card(link)

            if not bucket['name']:
                title = card.select_one(TITLE_SELECTOR)
                if title:
                    bucket['name'] = title.get_text(' ', strip=True)
            if not bucket['tagline']:
                tagline = card.select_one(TAGLINE_SELECTOR)
                if tagline:
                    bucket['tagline'] = tagline.get_text(' ', strip=True)
            if not bucket['image']:
                img = card.find('img')
                if img:
                    bucket['image'] = img.get('src', '')

        products = []
        for slug, data in buckets.items():
            product = self._parse_product({
                'slug': slug,
                'name': data['name'],
                'tagline': data['tagline'],
                'thumbnail_link': data['image'],
            })
            if product:
                products.append(product)
        return products

    @staticmethod
    def _find_card(link):
        """向上寻找包含标题或简介的卡片容器"""
        node = link
        for _ in range(6):
            if node is None or node.name in ('body', 'html'):
                return link
            if node.select_one(TITLE_SELECTOR) or node.select_one(TAGLINE_SELECTOR):
                return node
            node = node.parent
        return link

    # ---------- 字段解析 ----------

    def _parse_product(self, data: Dict) -> Optional[Product]:
        """解析榜单条目（也用于 HTML 回退构造出的同构字典）"""
        if not isinstance(data, dict):
            return None

        slug = (data.get('slug') or '').strip()
        name = (data.get('name') or '').strip()
        # 广告位没有 slug 或带 ad_type，混进赛道统计会污染结论
        if not slug or not name or data.get('ad_type'):
            return None

        tagline = (data.get('tagline') or '').strip()
        pricing = (data.get('pricing_type') or '').strip()
        category = (data.get('category_type') or '').strip() or 'New Launch'

        tags = ['fazier']
        if category:
            tags.append(category)
        if pricing:
            tags.append(pricing)

        return Product(
            id=f'fz_{slug}',
            name=name,
            description=tagline or name,
            url=f'{self.base_url}/launches/{slug}',
            platform='fazier',
            votes=self._to_int(data.get('upvotes_count')),
            comments=self._to_int(data.get('comments_count')),
            category=category,
            tags=tags,
            image=(data.get('thumbnail_link') or ''),
            created_at=(data.get('launch_date') or data.get('created_at') or ''),
            metadata={
                'slug': slug,
                'pricing': pricing,
                'source': 'fazier.com',
            },
        )

    @staticmethod
    def _to_int(value: Any) -> int:
        if value is None or isinstance(value, bool):
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _dedupe_keep_best(products: List[Product]) -> List[Product]:
        """同一产品可能同时上当日与本周榜，保留票数更高的那条"""
        best: Dict[str, Product] = {}
        for product in products:
            current = best.get(product.id)
            if current is None or product.votes > current.votes:
                best[product.id] = product
        return list(best.values())
