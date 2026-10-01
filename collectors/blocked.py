"""
被 Cloudflare 拦截的平台：公共基类

uneed.best 与 microlaunch.net 整站由 Cloudflare Bot Management 保护，
对非浏览器客户端（requests / curl，即使补齐浏览器请求头）恒返回 403，且都没有公开 API。
因此这两个采集器在 config.yaml 中默认关闭，只有在配好代理后才建议启用。

解析规则说明（重要）：
由于站点当前无法访问，无法离线取样，下面的解析按"每日榜单 + 产品卡片"的通用结构编写，
**尚未用真实页面验证过**。首次启用时请先跑：

    python main.py run -p uneed -v

确认日志里的解析条数与实际一致；若选择器不符，按真实 DOM 调整子类的 *_SELECTORS 即可。

代理生效方式：main.py 会把 config.yaml 的 proxy 段注入每个采集器（见 init_collectors），
只要能拿到稳定出口 IP（住宅代理通常可过），无需改动本文件。
"""

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseCollector, CollectorError, Product

logger = logging.getLogger(__name__)

# 卡片内的名称与简介候选选择器，按优先级尝试
NAME_SELECTORS = ('h3', 'h2', 'h4', 'a[class*=title]', 'span[class*=title]', 'div[class*=title]')
TAGLINE_SELECTORS = ('p', 'div[class*=desc]', 'span[class*=desc]', 'div[class*=tagline]')


class WafBlockedCollector(BaseCollector):
    """整站被 WAF 拦截的平台的公共基类"""

    # ---- 子类覆盖 ----
    HOME_PATH = '/'
    # 产品详情页的正则，必须带一个捕获组表示 slug
    PRODUCT_LINK_RE: re.Pattern = re.compile(r'$^')
    LINK_TEMPLATE = '{base}/tool/{slug}'

    def collect(self) -> List[Product]:
        response = self._fetch(f'{self.base_url}{self.HOME_PATH}')
        if response is None:
            raise CollectorError(self._blocked_hint())

        products = self._parse_listing(response.text)
        if not products:
            logger.warning(
                f'{self.platform_name}: 页面已取到但未解析出产品，选择器可能已失效，'
                f'请用 -v 查看日志并按真实 DOM 调整选择器'
            )

        unique = self._dedupe(products)
        logger.info(f'Parsed {len(unique)} products from {self.platform_name}')
        return unique[:self.max_items]

    def _blocked_hint(self) -> str:
        return (
            f'{self.base_url} 返回 403 或不可达：该站整站由 Cloudflare 保护，'
            f'requests 客户端无法直接访问，且无公开 API。'
            f'请在 config.yaml 的 proxy 段配置一个稳定出口的代理后再启用，'
            f'或保持 platforms.{self.platform_key}.enabled=false。'
        )

    @property
    def platform_key(self) -> str:
        return self.config.get('_platform_key') or self.platform_name.lower()

    def _parse_listing(self, html: str) -> List[Product]:
        soup = BeautifulSoup(html, 'html.parser')
        buckets: Dict[str, Dict] = {}

        for link in soup.find_all('a', href=self.PRODUCT_LINK_RE):
            match = self.PRODUCT_LINK_RE.search(link.get('href', ''))
            if not match:
                continue
            slug = match.group(1)
            bucket = buckets.setdefault(slug, {'name': '', 'tagline': '', 'image': '', 'url': ''})
            if not bucket['url']:
                bucket['url'] = urljoin(self.base_url, link.get('href', ''))
            card = self._find_card(link)
            self._enrich(bucket, link, card)

        return [
            product for product in (
                self._parse_product({**data, 'slug': slug})
                for slug, data in buckets.items()
            ) if product
        ]

    @staticmethod
    def _find_card(link):
        """向上寻找包含图片的卡片容器"""
        node = link
        for _ in range(5):
            if node is None or node.name in ('body', 'html'):
                return link
            if node.find('img'):
                return node
            node = node.parent
        return link

    @classmethod
    def _enrich(cls, bucket: Dict, link, card) -> None:
        if not bucket['name']:
            for selector in NAME_SELECTORS:
                elem = card.select_one(selector)
                if elem:
                    text = elem.get_text(' ', strip=True)
                    if 0 < len(text) <= 80:
                        bucket['name'] = text
                        break

        if not bucket['name']:
            img = card.find('img')
            if img and img.get('alt'):
                bucket['name'] = img['alt'].strip()

        if not bucket['name']:
            text = link.get_text(' ', strip=True)
            if 0 < len(text) <= 80:
                bucket['name'] = text

        if not bucket['tagline']:
            for selector in TAGLINE_SELECTORS:
                elem = card.select_one(selector)
                if elem:
                    text = elem.get_text(' ', strip=True)
                    if text and text != bucket['name'] and len(text) > 12:
                        bucket['tagline'] = text
                        break

        if not bucket['image']:
            img = card.find('img')
            if img:
                bucket['image'] = img.get('src', '')

    def _parse_product(self, data: Dict) -> Optional[Product]:
        slug = (data.get('slug') or '').strip()
        name = (data.get('name') or '').strip()
        if not slug or not name:
            return None

        return Product(
            id=f'{self.platform_key[:2]}_{slug}',
            name=name,
            description=(data.get('tagline') or f'{self.platform_name} product: {name}'),
            # 优先用页面上真实的 href；万一选择器与站点路径不符也不会拼出错误链接
            url=data.get('url') or self.LINK_TEMPLATE.format(base=self.base_url, slug=slug),
            platform=self.platform_key,
            # 站点不公开票数，热度按榜单位次估算
            votes=0,
            category='New Launch',
            tags=['launch', 'indie'],
            image=data.get('image', ''),
            metadata={
                'slug': slug,
                'source': self.base_url,
                'parser_verified': False,
            },
        )
