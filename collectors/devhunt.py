"""
DevHunt 数据收集器
专注于开发者工具

注意：devhunt.org 目前全站返回 Next.js 错误页，站点已不可用。
本收集器默认在 config.yaml 中关闭；若站点恢复，打开开关即可继续使用。
开发者工具维度的替代数据源见 github_trending.py。
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, CollectorError, Product

logger = logging.getLogger(__name__)

# Next.js 渲染失败时会输出这个 id，页面本身返回 200
ERROR_PAGE_MARKER = '__next_error__'


class DevHuntCollector(BaseCollector):
    """DevHunt 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://devhunt.org').rstrip('/')

    def collect(self) -> List[Product]:
        products = []
        unavailable = 0

        for path in ('/tools', '/leaderboard'):
            html = self._make_request(f"{self.base_url}{path}")
            if html is None:
                unavailable += 1
                continue
            if ERROR_PAGE_MARKER in html:
                logger.warning(f"DevHunt {path} returned an error page, skipping")
                unavailable += 1
                continue

            products.extend(self._parse_cards(html))

        if not products and unavailable:
            raise CollectorError(
                "devhunt.org is unavailable (all pages return an error page). "
                "Disable it in config.yaml or use github_trending instead."
            )

        unique = self._dedupe(products)
        logger.info(f"Parsed {len(unique)} unique tools from DevHunt")
        return unique[:self.max_items]

    def _parse_cards(self, html: str) -> List[Product]:
        soup = BeautifulSoup(html, 'html.parser')
        products = []

        for card in soup.find_all(['div', 'li'], class_=re.compile(r'tool|card|product|rank')):
            product = self._parse_card(card)
            if product:
                products.append(product)

        return products[:self.max_items]

    def _parse_card(self, card) -> Optional[Product]:
        """解析工具卡片"""
        try:
            title_elem = card.find(['h2', 'h3', 'h4', 'a'])
            if not title_elem:
                return None

            name = title_elem.get_text(strip=True)
            if not name or len(name) < 2 or len(name) > 80:
                return None

            link = card.find('a', href=True)
            url = link['href'] if link else ''
            if url and not url.startswith('http'):
                url = f"{self.base_url}{url}"

            desc_elem = card.find('p')
            description = desc_elem.get_text(strip=True) if desc_elem else ''

            votes = 0
            vote_text = card.find(string=re.compile(r'\d'))
            if vote_text:
                match = re.search(r'(\d[\d,]*)', vote_text)
                if match:
                    votes = int(match.group(1).replace(',', ''))

            slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:50]

            return Product(
                id=f"dh_{slug}",
                name=name,
                description=description or f"Developer tool from DevHunt: {name}",
                url=url or self.base_url,
                platform="devhunt",
                votes=votes,
                category="Developer Tools",
                tags=['developer-tools'],
                metadata={'slug': slug, 'source': 'devhunt.org'}
            )
        except Exception as e:
            logger.warning(f"Failed to parse DevHunt card: {e}")
            return None

    def _parse_product(self, data: Dict) -> Optional[Product]:
        return self._parse_card(data)
