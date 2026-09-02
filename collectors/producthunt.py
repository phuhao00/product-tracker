"""
Product Hunt 数据收集器
主数据源为官方 Atom feed，失败时回退到 hunted.space 页面解析
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, Product

logger = logging.getLogger(__name__)

ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}
# feed 中的 id 形如 tag:www.producthunt.com,2005:Post/1222307
POST_ID_RE = re.compile(r'Post/(\d+)')


class ProductHuntCollector(BaseCollector):
    """Product Hunt 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.feed_url = config.get('feed_url', 'https://www.producthunt.com/feed')
        self.fallback_url = config.get('alternative_source', 'https://hunted.space')

    def collect(self) -> List[Product]:
        products = self._collect_from_feed()

        if not products:
            logger.warning("Product Hunt feed returned nothing, trying hunted.space fallback")
            products = self._collect_from_fallback()

        return self._dedupe(products)[:self.max_items]

    def _collect_from_feed(self) -> List[Product]:
        root = self._make_xml_request(self.feed_url)
        if root is None:
            return []

        products = []
        for rank, entry in enumerate(root.findall('atom:entry', ATOM_NS), 1):
            try:
                product = self._parse_entry(entry, rank)
                if product:
                    products.append(product)
            except Exception as e:
                logger.warning(f"Failed to parse Product Hunt entry: {e}")

        logger.info(f"Parsed {len(products)} products from Product Hunt feed")
        return products

    def _parse_entry(self, entry, rank: int) -> Optional[Product]:
        """解析 Atom entry"""
        name = self._text(entry.find('atom:title', ATOM_NS))
        if not name:
            return None

        raw_id = self._text(entry.find('atom:id', ATOM_NS))
        match = POST_ID_RE.search(raw_id)
        post_id = match.group(1) if match else re.sub(r'[^a-z0-9]+', '-', name.lower())[:50]

        url = ''
        for link in entry.findall('atom:link', ATOM_NS):
            if link.get('rel', 'alternate') == 'alternate':
                url = link.get('href', '')
                break

        content = self._text(entry.find('atom:content', ATOM_NS))
        description = self._extract_description(content) or name

        author = self._text(entry.find('atom:author/atom:name', ATOM_NS))
        published = self._text(entry.find('atom:published', ATOM_NS))

        return Product(
            id=f"ph_{post_id}",
            name=name,
            description=description,
            url=url,
            platform="producthunt",
            # feed 不提供分类信息，留空由分析器归入 Uncategorized
            category="",
            tags=[],
            author=author,
            created_at=published,
            metadata={
                'feed_rank': rank,
                'source': 'producthunt.com/feed',
                'slug': url.rstrip('/').split('/')[-1] if url else '',
            }
        )

    @staticmethod
    def _extract_description(content: str) -> str:
        """content 是转义后的HTML，描述位于第一个段落"""
        if not content:
            return ''

        soup = BeautifulSoup(content, 'html.parser')
        for paragraph in soup.find_all('p'):
            text = paragraph.get_text(strip=True)
            # 末段是 "Discussion | Link" 导航，跳过
            if text and 'Discussion' not in text:
                return re.sub(r'\s+', ' ', text)
        return ''

    @staticmethod
    def _text(node) -> str:
        return (node.text or '').strip() if node is not None else ''

    def _collect_from_fallback(self) -> List[Product]:
        """hunted.space 榜单页回退"""
        products = []
        endpoints = [
            f"{self.fallback_url}/top-products/weekly/latest",
            f"{self.fallback_url}/top-products/monthly/latest",
        ]

        for endpoint in endpoints:
            html = self._make_request(endpoint)
            if html:
                products.extend(self._parse_fallback_page(html))

        return products

    def _parse_fallback_page(self, html: str) -> List[Product]:
        products = []
        soup = BeautifulSoup(html, 'html.parser')

        for link in soup.find_all('a', href=re.compile(r'^/dashboard/'))[:self.max_items]:
            try:
                product = self._parse_fallback_link(link)
                if product:
                    products.append(product)
            except Exception as e:
                logger.warning(f"Failed to parse fallback product: {e}")

        return products

    def _parse_fallback_link(self, link) -> Optional[Product]:
        slug = link.get('href', '').replace('/dashboard/', '').strip('/')
        if not slug:
            return None

        name = ''
        img = link.find('img')
        if img:
            name = img.get('alt', '').split(' - ')[0].strip()
        if not name:
            name = link.get_text(strip=True)
        if not name or len(name) < 2:
            return None

        description = ''
        if link.parent:
            desc_elem = link.parent.find('p')
            if desc_elem:
                description = desc_elem.get_text(strip=True)

        return Product(
            id=f"ph_{slug}",
            name=name,
            description=description or name,
            url=f"https://www.producthunt.com/products/{slug}",
            platform="producthunt",
            category="",
            image=img.get('src', '') if img else '',
            metadata={'slug': slug, 'source': 'hunted.space'}
        )

    def _parse_product(self, data: Dict) -> Optional[Product]:
        """解析 Product Hunt GraphQL API 返回的产品对象"""
        try:
            return Product(
                id=f"ph_{data.get('id', '')}",
                name=data.get('name', ''),
                description=data.get('tagline', ''),
                url=data.get('url', ''),
                platform="producthunt",
                votes=data.get('votesCount', 0),
                comments=data.get('commentsCount', 0),
                category=data.get('category', ''),
                tags=data.get('topics', []),
                metadata={'website': data.get('website', '')}
            )
        except Exception as e:
            logger.error(f"Failed to parse product data: {e}")
            return None
