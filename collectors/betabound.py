"""
Betabound 数据收集器

偏向招募真实测试员（Beta Testers）进行深度体验与反馈的平台，
发布的是待测产品而非成品榜单，适合找第一批种子用户之前先验证需求。

站点是 WordPress，提供官方 RSS（/feed/，一次 10 条），
分类（category）会标出是测试机会还是产品发布。
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, Product
from .rss import parse_feed

logger = logging.getLogger(__name__)

# 链接尾部常带 -2 之类的重名后缀，作为去重键时保留原样即可
SLUG_RE = re.compile(r'/([^/]+)/?$')


class BetaBoundCollector(BaseCollector):
    """Betabound 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://www.betabound.com').rstrip('/')
        self.feed_url = config.get('feed_url', f'{self.base_url}/feed/')

    def collect(self) -> List[Product]:
        root = self._make_xml_request(self.feed_url)
        if root is None:
            return []

        products = []
        for entry in parse_feed(root):
            product = self._parse_product(entry)
            if product:
                products.append(product)

        unique = self._dedupe(products)
        logger.info(f'Parsed {len(unique)} beta opportunities from Betabound')
        return unique[:self.max_items]

    def _parse_product(self, data: Dict) -> Optional[Product]:
        link = (data.get('link') or '').strip()
        title = (data.get('title') or '').strip()
        if not link or not title:
            return None

        match = SLUG_RE.search(link.rstrip('/'))
        slug = match.group(1) if match else re.sub(r'\W+', '-', title)[:40].strip('-')

        categories = data.get('categories') or []
        category = categories[0] if categories else 'Beta Test'

        return Product(
            id=f'bb_{slug}',
            name=title,
            description=self._clean_html(data.get('description') or '') or title,
            url=link,
            platform='betabound',
            # 站点不公开票数，热度按榜单位次估算
            votes=0,
            category=category,
            tags=['beta', 'testing', category.lower()],
            author=(data.get('author') or '').strip(),
            created_at=(data.get('published') or '').strip(),
            metadata={
                'slug': slug,
                'all_categories': categories,
                'source': 'betabound.com',
            },
        )

    @staticmethod
    def _clean_html(raw: str) -> str:
        """RSS 正文是 HTML，且尾部会重复一段 "The post ... appeared first on ..." """
        if not raw:
            return ''
        text = BeautifulSoup(raw, 'html.parser').get_text(' ')
        text = re.sub(r'The post\s+.*?appeared first on\s+.*?\.', '', text, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', text).strip()
