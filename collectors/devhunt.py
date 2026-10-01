"""
DevHunt 数据收集器

开发者们因为厌倦 Product Hunt 的商业化而自建的平台，专门收录开发工具、开源项目与 SaaS 接口。

devhunt.org 在 2025 年改版后已恢复可用（旧版全站返回 Next.js 错误页，本项目曾据此默认关闭），
并且改版后把完整产品数据放进了 Next.js 的 flight 内联负载里 —— 含票数、浏览量、
分类与定价，比抓 HTML 可靠得多，因此优先解析内联数据，站点改版时再回退到 HTML。

产品详情页是单数 /tool/<slug>，与分类页复数 /tools/<category> 只差一个字母，解析时必须区分。
"""

import json
import logging
import re
from typing import Dict, Iterator, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, CollectorError, Product

logger = logging.getLogger(__name__)

# Next.js 渲染失败时会输出这个 id，页面本身仍返回 200
ERROR_PAGE_MARKER = '__next_error__'
# 产品页是单数 /tool/<slug>；分类页是复数 /tools/<category>，不能混
PRODUCT_RE = re.compile(r'^/tool/([^/?#]+)$')
# RSC flight 负载以字符串常量的形式分片推送，拼起来才是完整 JSON
FLIGHT_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[\d+,\s*("(?:[^"\\]|\\.)*")\]\)')
# 产品对象在负载里的起始锚点
OBJECT_ANCHOR = '{"id":'
IMPRESSIONS_RE = re.compile(r'([\d,]+)\s+impressions?', re.IGNORECASE)


class DevHuntCollector(BaseCollector):
    """DevHunt 数据收集器"""

    # 首页给当日榜，/all-dev-tools 给完整库，/upcoming 给即将发布
    LIST_PATHS = ('/', '/all-dev-tools', '/upcoming')

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://devhunt.org').rstrip('/')

    def collect(self) -> List[Product]:
        products: List[Product] = []
        unavailable = 0

        for path in self.LIST_PATHS:
            html = self._make_request(f'{self.base_url}{path}')
            if html is None or ERROR_PAGE_MARKER in html:
                unavailable += 1
                continue

            found = self._collect_from_flight(html, path)
            if not found:
                logger.debug(f'DevHunt {path}: flight 负载不可用，回退到 HTML 解析')
                found = self._collect_from_html(html, path)

            logger.debug(f'DevHunt {path}: parsed {len(found)} tools')
            products.extend(found)

        if not products and unavailable:
            raise CollectorError(
                'devhunt.org 不可用（所有榜单页均返回错误页）。'
                '请在 config.yaml 中关闭该平台，或改用 github_trending。'
            )

        unique = self._dedupe(products)
        logger.info(f'Parsed {len(unique)} unique tools from DevHunt')
        return unique[:self.max_items]

    # ---------- 首选：Next.js flight 内联数据 ----------

    def _collect_from_flight(self, html: str, path: str) -> List[Product]:
        products = []
        for obj in self._iter_flight_objects(html):
            product = self._parse_product({**obj, 'path': path})
            if product:
                products.append(product)
        return products

    @classmethod
    def _iter_flight_objects(cls, html: str) -> Iterator[Dict]:
        """从 flight 负载里逐个抠出产品对象（对象内含嵌套，需按括号配对切分）"""
        blob = cls._read_flight_blob(html)
        if not blob:
            return

        covered: List[tuple] = []
        for match in re.finditer(re.escape(OBJECT_ANCHOR), blob):
            start = match.start()
            # 嵌套对象（如 product_categories）会被外层先覆盖，直接跳过
            if any(begin <= start < end for begin, end in covered):
                continue
            end = cls._matching_brace(blob, start)
            if end is None:
                continue
            covered.append((start, end))
            try:
                obj = json.loads(blob[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(obj, dict) and obj.get('slug') and obj.get('name'):
                yield obj

    @staticmethod
    def _read_flight_blob(html: str) -> str:
        parts = []
        for fragment in FLIGHT_PUSH_RE.findall(html):
            try:
                parts.append(json.loads(fragment))
            except (json.JSONDecodeError, ValueError):
                continue
        return ''.join(parts)

    @staticmethod
    def _matching_brace(text: str, start: int) -> Optional[int]:
        """从 start 处的 '{' 开始，找到配对的 '}'（跳过字符串内的括号）"""
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return index
        return None

    # ---------- 回退：HTML 卡片 ----------

    def _collect_from_html(self, html: str, path: str) -> List[Product]:
        soup = BeautifulSoup(html, 'html.parser')
        buckets: Dict[str, Dict] = {}

        for link in soup.find_all('a', href=PRODUCT_RE):
            match = PRODUCT_RE.match(link.get('href', ''))
            if not match:
                continue
            slug = match.group(1)
            bucket = buckets.setdefault(slug, {'name': '', 'tagline': '', 'image': ''})
            self._enrich_from_link(bucket, link)

        return [
            product for product in (
                self._parse_product({
                    'slug': slug,
                    'name': data['name'],
                    'slogan': data['tagline'],
                    'logo_url': data['image'],
                    'path': path,
                })
                for slug, data in buckets.items()
            ) if product
        ]

    @classmethod
    def _enrich_from_link(cls, bucket: Dict, link) -> None:
        """从链接自身抽字段：两套布局的差异都收敛在这里"""
        img = link.find('img')
        if img:
            if img.get('alt') and not bucket['name']:
                bucket['name'] = img['alt'].strip()
            if img.get('src') and not bucket['image']:
                bucket['image'] = img['src']

        heading = link.find('h3')
        if heading and not bucket['name']:
            bucket['name'] = heading.get_text(' ', strip=True)

        name_span = link.select_one('span.font-medium') or link.select_one('span.text-slate-100')
        if name_span and not bucket['name']:
            bucket['name'] = name_span.get_text(' ', strip=True)

        if not bucket['tagline']:
            paragraph = link.find('p')
            if paragraph:
                bucket['tagline'] = paragraph.get_text(' ', strip=True)

        if not bucket['tagline']:
            # /upcoming 布局："DevUtilX · 100+ free online developer tools"
            spans = [s.get_text(' ', strip=True) for s in link.find_all('span')]
            tail = [s for s in spans if s and s != bucket['name']]
            if tail:
                bucket['tagline'] = tail[-1].lstrip('·').strip()

    # ---------- 字段解析 ----------

    def _parse_product(self, data: Dict) -> Optional[Product]:
        """解析产品对象（内联 JSON 与 HTML 回退共用同一套字段）"""
        slug = (data.get('slug') or '').strip()
        name = (data.get('name') or '').strip()
        if not slug or not name:
            return None

        slogan = (data.get('slogan') or '').strip()
        description = (data.get('description') or '').strip()
        categories = data.get('product_categories') or []
        category_names = [
            (c.get('name') or '').strip() for c in categories if isinstance(c, dict)
        ]
        pricing = data.get('product_pricing_types') or {}
        pricing_title = (pricing.get('title') or '').strip() if isinstance(pricing, dict) else ''

        tags = ['devtool']
        tags.extend(name_.lower() for name_ in category_names if name_)
        if pricing_title:
            tags.append(pricing_title.lower())

        return Product(
            id=f'dh_{slug}',
            name=name,
            # 列表页展示 slogan，详情页才有长描述，优先用 slogan 保持一行可读
            description=slogan or description or f'Developer tool on DevHunt: {name}',
            url=f'{self.base_url}/tool/{slug}',
            platform='devhunt',
            votes=self._to_int(data.get('votes_count')),
            category=category_names[0] if category_names else 'Developer Tool',
            tags=tags,
            image=(data.get('logo_url') or data.get('image') or ''),
            created_at=(data.get('launch_date') or ''),
            metadata={
                'slug': slug,
                'slogan': slogan,
                'detail': description[:500],
                'categories': category_names,
                'pricing': pricing_title,
                'views': self._to_int(data.get('views_count')),
                'week': data.get('week'),
                'demo_url': data.get('demo_url', ''),
                'list_path': data.get('path', ''),
                'source': 'devhunt.org',
            },
        )

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
