"""
BetaList 数据收集器
抓取早期/内测阶段的初创产品
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, Product

logger = logging.getLogger(__name__)

# 产品详情页路径形如 /startups/<slug>
SLUG_RE = re.compile(r'/startups/([^/?#]+)')
# 站点使用 Tailwind，名称与描述靠工具类区分而非语义化类名
NAME_SELECTORS = ('div.font-medium', 'h2', 'h3', 'div[class*="font-medium"]')
DESC_SELECTORS = ('div[class*="text-gray-600"]', 'div[class*="text-gray-400"]', 'p')
# 推广徽章会与正文连在一起（如 "Talmaara.comBOOSTED"）
BADGE_RE = re.compile(r'\s*(BOOSTED|PROMOTED|FEATURED|SPONSORED)\s*', re.IGNORECASE)


class BetaListCollector(BaseCollector):
    """BetaList 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://betalist.com').rstrip('/')

    def collect(self) -> List[Product]:
        products = []

        for path in ('', '/?page=2'):
            html = self._make_request(f"{self.base_url}{path}")
            if html:
                found = self._parse_listing(html)
                logger.debug(f"BetaList {path or '/'}: parsed {len(found)} products")
                products.extend(found)

        unique = self._dedupe(products)
        logger.info(f"Parsed {len(unique)} unique products from BetaList")
        return unique[:self.max_items]

    def _parse_listing(self, html: str) -> List[Product]:
        """解析产品列表页

        同一产品在页面上有多个链接（图片、标题、整卡覆盖层），
        因此按 slug 聚合，从各处补全字段。
        """
        soup = BeautifulSoup(html, 'html.parser')
        buckets: Dict[str, Dict] = {}

        for link in soup.find_all('a', href=SLUG_RE):
            match = SLUG_RE.search(link.get('href', ''))
            if not match:
                continue

            slug = match.group(1)
            # 排除 /startups/xxx/follow 之类的操作链接
            if slug in ('follow', 'unfollow') or link.get('data-controller') == 'form':
                continue

            bucket = buckets.setdefault(slug, {'name': '', 'description': '', 'image': ''})
            self._enrich(bucket, link)

        products = []
        for slug, data in buckets.items():
            product = self._build_product(slug, data)
            if product:
                products.append(product)

        return products

    def _enrich(self, bucket: Dict, link) -> None:
        """从一个链接及其所属卡片中补全产品字段"""
        if not bucket['name']:
            bucket['name'] = self._extract_name(link)

        card = self._find_card(link)
        if not card:
            return

        if not bucket['name']:
            bucket['name'] = self._extract_name(card)

        if not bucket['description']:
            bucket['description'] = self._extract_description(card, bucket['name'])

        if not bucket['image']:
            img = card.find('img')
            if img:
                bucket['image'] = img.get('src', '')

    @staticmethod
    def _find_card(link):
        """向上寻找包含缩略图的卡片容器"""
        node = link
        for _ in range(5):
            node = node.parent
            if node is None or node.name in ('body', 'html'):
                return None
            if node.find('img'):
                return node
        return None

    @classmethod
    def _extract_name(cls, scope) -> str:
        for selector in NAME_SELECTORS:
            elem = scope.select_one(selector)
            if elem:
                text = cls._strip_badges(elem.get_text(strip=True))
                if text:
                    return text

        text = cls._strip_badges(scope.get_text(strip=True))
        return text if 0 < len(text) <= 60 else ''

    @classmethod
    def _extract_description(cls, card, name: str) -> str:
        for selector in DESC_SELECTORS:
            for elem in card.select(selector):
                text = cls._strip_badges(elem.get_text(strip=True))
                if text and text != name and len(text) > 15:
                    return text

        # 首页的特色卡片用了另一套工具类，退化为按文本长度挑选叶子节点
        for elem in card.find_all(['div', 'p', 'span']):
            if elem.find(['div', 'p', 'span']):
                continue
            text = cls._strip_badges(elem.get_text(strip=True))
            if text != name and 15 < len(text) <= 200:
                return text
        return ''

    @staticmethod
    def _strip_badges(text: str) -> str:
        return BADGE_RE.sub(' ', text or '').strip()

    def _build_product(self, slug: str, data: Dict) -> Optional[Product]:
        name = data['name'] or slug.replace('-', ' ').title()
        if len(name) < 2:
            return None

        image = data['image']
        if image and image.startswith('/'):
            image = f"{self.base_url}{image}"

        return Product(
            id=f"bl_{slug}",
            name=name,
            description=data['description'] or f"Early-stage startup on BetaList: {name}",
            url=f"{self.base_url}/startups/{slug}",
            platform="betalist",
            category="Early Stage",
            tags=['beta', 'early-access'],
            image=image,
            metadata={'slug': slug, 'source': 'betalist.com'}
        )

    def _parse_product(self, data: Dict) -> Optional[Product]:
        """从已解析的字段字典构建产品"""
        slug = data.get('slug')
        if not slug:
            return None
        return self._build_product(slug, {
            'name': data.get('name', ''),
            'description': data.get('description', ''),
            'image': data.get('image', ''),
        })
