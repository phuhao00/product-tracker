"""
新趣集（Xinquji）数据收集器

国内较知名的"中国版 Product Hunt"，收录新鲜的互联网产品与创意工具，中文语料，
适合补充国内视角的产品灵感。站点提供官方 RSS（/rss，一次 20 条），
比抓 HTML 稳定，且带发布时间。
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, Product
from .rss import parse_feed

logger = logging.getLogger(__name__)

POST_ID_RE = re.compile(r'/posts/(\d+)')
# RSS 里的链接带 utm 参数，展示时去掉
TRACKING_RE = re.compile(r'[?&]utm_[^&]*')


class XinqujiCollector(BaseCollector):
    """新趣集数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://xinquji.com').rstrip('/')
        self.feed_url = config.get('feed_url', f'{self.base_url}/rss')

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
        logger.info(f'Parsed {len(unique)} products from 新趣集')
        return unique[:self.max_items]

    def _parse_product(self, data: Dict) -> Optional[Product]:
        link = (data.get('link') or '').strip()
        title = (data.get('title') or '').strip()
        if not link or not title:
            return None

        match = POST_ID_RE.search(link)
        # 没有数字 ID 时用标题兜底，保证去重键稳定
        slug = match.group(1) if match else re.sub(r'\W+', '-', title)[:40].strip('-')
        clean_url = TRACKING_RE.sub('', link).rstrip('?&')

        description = self._clean_html(data.get('description') or '')

        return Product(
            id=f'xq_{slug}',
            name=title,
            description=description or title,
            url=clean_url,
            platform='xinquji',
            # 站点不公开票数，热度按榜单位次估算
            votes=0,
            category='新产品',
            tags=['china', 'product-discovery'],
            author=(data.get('author') or '').strip(),
            created_at=(data.get('published') or '').strip(),
            metadata={
                'slug': slug,
                'categories': data.get('categories') or [],
                'source': 'xinquji.com',
            },
        )

    @staticmethod
    def _clean_html(raw: str) -> str:
        if not raw:
            return ''
        text = BeautifulSoup(raw, 'html.parser').get_text(' ')
        return re.sub(r'\s+', ' ', text).strip()
