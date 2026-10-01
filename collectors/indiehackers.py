"""
Indie Hackers 数据收集器

独立开发者的精神家园，这里的产品倾向于「公开构建」（Build in Public），
站点会把创始人经 Stripe 验证的月收入（MRR）直接挂在产品卡片上，
因此它是本项目中唯一带真实营收维度的数据源 —— 用来判断"谁真的赚到钱了"。

产品列表页用 BEM 命名（product-card__*），选择器稳定，不依赖工具类顺序。
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, Product

logger = logging.getLogger(__name__)

CARD_SELECTOR = '.product-card'
NAME_SELECTOR = '.product-card__name'
TAGLINE_SELECTOR = '.product-card__tagline'
REVENUE_SELECTOR = '.product-card__revenue-number'
REVENUE_NOTE_SELECTOR = '.product-card__revenue-explanation'
LINK_SELECTOR = "a[href*='/product/']"
SLUG_RE = re.compile(r'/product/([^/?#]+)')
# "$1,234" / "$12k" / "$1.5M" 都出现过，统一折算成美元整数
MONEY_RE = re.compile(r'\$\s*([\d,.]+)\s*([kKmM])?')


class IndieHackersCollector(BaseCollector):
    """Indie Hackers 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://www.indiehackers.com').rstrip('/')
        # 站点默认按收入排序，也支持 newest 之类的排序参数
        self.list_path = config.get('list_path', '/products')

    def collect(self) -> List[Product]:
        products: List[Product] = []

        html = self._make_request(f'{self.base_url}{self.list_path}')
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        for card in soup.select(CARD_SELECTOR):
            product = self._parse_card(card)
            if product:
                products.append(product)

        unique = self._dedupe(products)
        logger.info(f'Parsed {len(unique)} products from Indie Hackers')
        return unique[:self.max_items]

    def _parse_card(self, card) -> Optional[Product]:
        try:
            link = card.select_one(LINK_SELECTOR)
            if not link:
                return None
            match = SLUG_RE.search(link.get('href', ''))
            if not match:
                return None
            slug = match.group(1)

            name_elem = card.select_one(NAME_SELECTOR)
            name = name_elem.get_text(strip=True) if name_elem else ''
            if not name:
                return None

            tagline_elem = card.select_one(TAGLINE_SELECTOR)
            tagline = tagline_elem.get_text(strip=True) if tagline_elem else ''

            revenue_elem = card.select_one(REVENUE_SELECTOR)
            mrr = self._parse_money(revenue_elem.get_text(' ', strip=True)) if revenue_elem else 0

            note_elem = card.select_one(REVENUE_NOTE_SELECTOR)
            revenue_note = note_elem.get_text(' ', strip=True) if note_elem else ''

            image = ''
            img = card.find('img')
            if img:
                image = img.get('src', '')

            return self._parse_product({
                'slug': slug,
                'name': name,
                'tagline': tagline,
                'mrr': mrr,
                'revenue_note': revenue_note,
                'image': image,
            })
        except Exception as e:
            logger.warning(f'Failed to parse Indie Hackers card: {e}')
            return None

    def _parse_product(self, data: Dict) -> Optional[Product]:
        slug = (data.get('slug') or '').strip()
        name = (data.get('name') or '').strip()
        if not slug or not name:
            return None

        mrr = int(data.get('mrr') or 0)
        tagline = (data.get('tagline') or '').strip()

        tags = ['indie']
        if data.get('revenue_note'):
            tags.append(str(data['revenue_note']).lower())

        return Product(
            id=f'ih_{slug}',
            name=name,
            description=tagline or f'Indie product on Indie Hackers: {name}',
            url=f'{self.base_url}/product/{slug}',
            platform='indiehackers',
            # MRR 是该站的排序口径，直接当作热度值参与平台内百分位归一化
            votes=mrr,
            category='Indie Product',
            tags=tags,
            image=data.get('image', ''),
            metadata={
                'slug': slug,
                'mrr': mrr,
                'revenue_note': data.get('revenue_note', ''),
                'source': 'indiehackers.com',
            },
        )

    @staticmethod
    def _parse_money(text: str) -> int:
        """把 "$1,234" / "$12k" 折算成美元整数"""
        match = MONEY_RE.search(text or '')
        if not match:
            return 0
        try:
            value = float(match.group(1).replace(',', ''))
        except ValueError:
            return 0
        suffix = (match.group(2) or '').lower()
        if suffix == 'k':
            value *= 1_000
        elif suffix == 'm':
            value *= 1_000_000
        return int(value)
