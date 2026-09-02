"""
GitHub Trending 数据收集器
以开源项目热度作为开发者工具的风向标（替代已下线的 DevHunt）
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from .base import BaseCollector, Product

logger = logging.getLogger(__name__)

# "22,095 stars this week" —— 榜单周期内的新增星数
PERIOD_STARS_RE = re.compile(r'([\d,]+)\s+stars?\s+(?:this|today)')


class GitHubTrendingCollector(BaseCollector):
    """GitHub Trending 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://github.com').rstrip('/')
        self.periods = config.get('periods', ['daily', 'weekly'])
        self.languages = config.get('languages', [''])

    def collect(self) -> List[Product]:
        products = []

        for period in self.periods:
            for language in self.languages:
                url = f"{self.base_url}/trending"
                if language:
                    url += f"/{language}"
                url += f"?since={period}"

                html = self._make_request(url)
                if not html:
                    continue

                found = self._parse_trending(html, period)
                logger.debug(f"GitHub Trending {period}/{language or 'all'}: {len(found)} repos")
                products.extend(found)

        # 同一仓库可能同时上日榜和周榜，取周期内新增星数更高的那条
        products.sort(key=lambda p: p.votes, reverse=True)
        unique = self._dedupe(products)
        logger.info(f"Parsed {len(unique)} unique repos from GitHub Trending")
        return unique[:self.max_items]

    def _parse_trending(self, html: str, period: str) -> List[Product]:
        soup = BeautifulSoup(html, 'html.parser')
        products = []

        for row in soup.select('article.Box-row'):
            product = self._parse_row(row, period)
            if product:
                products.append(product)

        return products

    def _parse_row(self, row, period: str) -> Optional[Product]:
        """解析单个仓库条目"""
        try:
            link = row.select_one('h2 a')
            if not link:
                return None

            repo_path = link.get('href', '').strip('/')
            if not repo_path or '/' not in repo_path:
                return None

            owner, _, repo = repo_path.partition('/')
            desc_elem = row.select_one('p')
            description = desc_elem.get_text(strip=True) if desc_elem else ''

            language = ''
            lang_elem = row.select_one('span[itemprop="programmingLanguage"]')
            if lang_elem:
                language = lang_elem.get_text(strip=True)

            total_stars = self._parse_count(row.select_one('a[href$="/stargazers"]'))
            forks = self._parse_count(row.select_one('a[href$="/forks"]'))

            # 用周期内新增星数作为热度票数，比总星数更能反映"当下热门"
            period_stars = 0
            period_elem = row.select_one('span.d-inline-block.float-sm-right')
            if period_elem:
                match = PERIOD_STARS_RE.search(period_elem.get_text(strip=True))
                if match:
                    period_stars = int(match.group(1).replace(',', ''))

            tags = ['open-source']
            if language:
                tags.append(language.lower())

            return Product(
                id=f"gh_{repo_path.replace('/', '_')}",
                name=repo,
                description=description or f"Trending GitHub repository: {repo_path}",
                url=f"{self.base_url}/{repo_path}",
                platform="github_trending",
                votes=period_stars or total_stars,
                category=language or "Open Source",
                tags=tags,
                author=owner,
                metadata={
                    'repo': repo_path,
                    'language': language,
                    'total_stars': total_stars,
                    'period_stars': period_stars,
                    'forks': forks,
                    'period': period,
                    'source': 'github.com/trending',
                }
            )
        except Exception as e:
            logger.warning(f"Failed to parse GitHub Trending row: {e}")
            return None

    @staticmethod
    def _parse_count(elem) -> int:
        if not elem:
            return 0
        match = re.search(r'([\d,]+)', elem.get_text(strip=True))
        return int(match.group(1).replace(',', '')) if match else 0

    def _parse_product(self, data: Dict) -> Optional[Product]:
        """解析 GitHub REST API 的 repository 对象"""
        try:
            repo_path = data.get('full_name', '')
            if not repo_path:
                return None

            return Product(
                id=f"gh_{repo_path.replace('/', '_')}",
                name=data.get('name', ''),
                description=data.get('description') or '',
                url=data.get('html_url', ''),
                platform="github_trending",
                votes=data.get('stargazers_count', 0),
                category=data.get('language') or 'Open Source',
                tags=data.get('topics', []) or ['open-source'],
                author=(data.get('owner') or {}).get('login', ''),
                created_at=data.get('created_at', ''),
                metadata={
                    'repo': repo_path,
                    'forks': data.get('forks_count', 0),
                    'source': 'api.github.com',
                }
            )
        except Exception as e:
            logger.error(f"Failed to parse repository data: {e}")
            return None
