"""
StartuPage 数据收集器

主打持续性发现而非单日发布：创始人可以把经 Stripe 验证的月收入（MRR）挂到项目上，
榜单按 MRR 排序（/leaderboard?tab=startups），因此它衡量的是"真实收入"而不是"一日热度"。

页面是 Next.js 静态输出，榜单行直接可解析：名称在 a.font-semibold、简介在 div.flex-1 > p、
MRR 在右侧 div.text-right > p。
"""

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from .base import BaseCollector, Product

logger = logging.getLogger(__name__)

STARTUP_RE = re.compile(r'^/startups/([^/?#]+)')
MONEY_RE = re.compile(r'\$\s*([\d,.]+)\s*([kKmM])?')
# 行容器的特征是"包含金额且文本不长"，用它把行框出来
MAX_ROW_TEXT_LEN = 320


class StartuPageCollector(BaseCollector):
    """StartuPage 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://startupa.ge').rstrip('/')
        self.list_path = config.get('list_path', '/leaderboard?tab=startups')

    def collect(self) -> List[Product]:
        html = self._make_request(f'{self.base_url}{self.list_path}')
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        buckets: Dict[str, Dict] = {}

        for link in soup.find_all('a', href=STARTUP_RE):
            slug = STARTUP_RE.match(link.get('href', '')).group(1)
            bucket = buckets.setdefault(slug, {
                'name': '', 'tagline': '', 'image': '', 'mrr': 0,
            })
            row = self._find_row(link)
            if row is not None:
                self._enrich_from_row(bucket, row, link)

        products = []
        for slug, data in buckets.items():
            product = self._parse_product({**data, 'slug': slug})
            if product:
                products.append(product)

        unique = self._dedupe(products)
        logger.info(f'Parsed {len(unique)} startups from StartuPage')
        return unique[:self.max_items]

    @staticmethod
    def _find_row(link):
        """向上找到包含金额的那一行"""
        node = link
        for _ in range(6):
            if node is None or node.name in ('body', 'html'):
                return None
            text = node.get_text(' ', strip=True)
            if MONEY_RE.search(text) and len(text) < MAX_ROW_TEXT_LEN:
                return node
            node = node.parent
        return None

    @classmethod
    def _enrich_from_row(cls, bucket: Dict, row, link) -> None:
        if not bucket['name']:
            name_elem = row.select_one('a.font-semibold')
            if name_elem:
                bucket['name'] = name_elem.get_text(' ', strip=True)
        if not bucket['name']:
            img = row.find('img')
            if img and img.get('alt'):
                bucket['name'] = img['alt'].strip()

        if not bucket['tagline']:
            tagline_elem = row.select_one('div.flex-1 p') or row.select_one('p.text-xs')
            if tagline_elem:
                bucket['tagline'] = tagline_elem.get_text(' ', strip=True)

        if not bucket['mrr']:
            mrr_elem = row.select_one('div.text-right p')
            if mrr_elem:
                bucket['mrr'] = cls._parse_money(mrr_elem.get_text(' ', strip=True))

        if not bucket['image']:
            img = row.find('img')
            if img:
                bucket['image'] = cls._unwrap_next_image(img.get('src', ''))

    @staticmethod
    def _unwrap_next_image(src: str) -> str:
        """Next.js 的 /_next/image?url=... 把真实地址藏在查询参数里"""
        if not src or '/_next/image' not in src:
            return src
        query = parse_qs(urlparse(src).query)
        raw = (query.get('url') or [''])[0]
        return unquote(raw) or src

    def _parse_product(self, data: Dict) -> Optional[Product]:
        slug = (data.get('slug') or '').strip()
        name = (data.get('name') or '').strip()
        if not slug or not name:
            return None

        mrr = int(data.get('mrr') or 0)
        return Product(
            id=f'sa_{slug}',
            name=name,
            description=(data.get('tagline') or f'Startup on StartuPage: {name}'),
            url=f'{self.base_url}/startups/{slug}',
            platform='startupage',
            # MRR 是该榜的排序口径，作为热度值参与平台内百分位归一化
            votes=mrr,
            category='Indie Startup',
            tags=['indie', 'mrr'],
            image=data.get('image', ''),
            metadata={
                'slug': slug,
                'mrr': mrr,
                'source': 'startupa.ge',
            },
        )

    @staticmethod
    def _parse_money(text: str) -> int:
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
