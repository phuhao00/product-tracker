"""
Hacker News 数据收集器
收集 Show HN 类别的产品

主数据源为 Algolia 搜索 API：一次请求即可拿到标题、票数与评论数，
比逐条请求 Firebase API 快两个数量级。
"""

import logging
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from keywords import contains_keyword, normalize_text

from .base import BaseCollector, Product

logger = logging.getLogger(__name__)

# 从标题与正文中识别技术栈/品类标签，按词边界匹配
TAG_KEYWORDS = {
    'ai': 'AI',
    'machine learning': 'Machine Learning',
    'llm': 'LLM',
    'gpt': 'GPT',
    'agent': 'Agent',
    'open source': 'Open Source',
    'self hosted': 'Self-Hosted',
    'rust': 'Rust',
    'python': 'Python',
    'javascript': 'JavaScript',
    'typescript': 'TypeScript',
    'go': 'Go',
    'api': 'API',
    'saas': 'SaaS',
    'cli': 'CLI',
    'database': 'Database',
    'developer': 'Developer',
    'productivity': 'Productivity',
    'automation': 'Automation',
    'security': 'Security',
}


class HackerNewsCollector(BaseCollector):
    """Hacker News 数据收集器"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.api_base = config.get('api_endpoint', 'https://hacker-news.firebaseio.com/v0')
        self.search_api = config.get('search_endpoint', 'https://hn.algolia.com/api/v1')
        self.window_days = config.get('window_days', 7)

    def collect(self) -> List[Product]:
        products = self._collect_from_search()

        if not products:
            logger.warning("Algolia search returned nothing, falling back to Firebase API")
            products = self._collect_from_firebase()

        return self._dedupe(products)[:self.max_items]

    def _collect_from_search(self) -> List[Product]:
        """按时间窗口拉取 Show HN，再按票数本地排序"""
        since = int(time.time() - self.window_days * 86400)
        # 多取一些候选，保证按票数排序后有足够梯度
        hits_per_page = min(max(self.max_items * 4, 50), 200)
        url = (
            f"{self.search_api}/search_by_date"
            f"?tags=show_hn&numericFilters=created_at_i>{since}&hitsPerPage={hits_per_page}"
        )

        data = self._make_json_request(url)
        if not isinstance(data, dict):
            return []

        products = []
        for hit in data.get('hits', []):
            product = self._parse_search_hit(hit)
            if product:
                products.append(product)

        products.sort(key=lambda p: (p.votes, p.comments), reverse=True)
        logger.info(
            f"Parsed {len(products)} Show HN posts from the last {self.window_days} days"
        )
        return products

    def _parse_search_hit(self, hit: Dict) -> Optional[Product]:
        """解析 Algolia 命中记录"""
        try:
            item_id = hit.get('objectID') or hit.get('story_id')
            title = (hit.get('title') or '').strip()
            if not item_id or not title:
                return None

            hn_url = f"https://news.ycombinator.com/item?id={item_id}"
            url = hit.get('url') or hn_url
            text = self._clean_text(hit.get('story_text') or hit.get('comment_text') or '')
            name = self._clean_title(title)

            return Product(
                id=f"hn_{item_id}",
                name=name,
                description=(text[:500] or name),
                url=url,
                platform="hackernews",
                votes=hit.get('points') or 0,
                comments=hit.get('num_comments') or 0,
                category="Show HN",
                tags=self._extract_tags(title, text),
                author=hit.get('author', ''),
                created_at=hit.get('created_at', ''),
                metadata={
                    'hn_item_id': item_id,
                    'discussion_url': hn_url,
                    'source': 'hn.algolia.com',
                }
            )
        except Exception as e:
            logger.warning(f"Failed to parse HN search hit: {e}")
            return None

    def _collect_from_firebase(self) -> List[Product]:
        """Firebase 官方 API 回退：需逐条请求，较慢"""
        story_ids = self._make_json_request(f"{self.api_base}/showstories.json")
        if not isinstance(story_ids, list):
            return []

        products = []
        for item_id in story_ids[:self.max_items]:
            item_data = self._make_json_request(f"{self.api_base}/item/{item_id}.json")
            if item_data:
                product = self._parse_product(item_data)
                if product:
                    products.append(product)

        products.sort(key=lambda p: (p.votes, p.comments), reverse=True)
        return products

    def _parse_product(self, data: Dict) -> Optional[Product]:
        """解析 Firebase item 对象"""
        try:
            item_id = data.get('id', '')
            title = (data.get('title') or '').strip()
            if not item_id or not title:
                return None

            text = self._clean_text(data.get('text') or '')
            created = data.get('time', 0)
            hn_url = f"https://news.ycombinator.com/item?id={item_id}"
            name = self._clean_title(title)

            return Product(
                id=f"hn_{item_id}",
                name=name,
                description=(text[:500] or name),
                url=data.get('url') or hn_url,
                platform="hackernews",
                votes=data.get('score', 0),
                comments=data.get('descendants', 0),
                category="Show HN",
                tags=self._extract_tags(title, text),
                author=data.get('by', ''),
                created_at=datetime.fromtimestamp(created).isoformat() if created else '',
                metadata={
                    'hn_item_id': item_id,
                    'discussion_url': hn_url,
                    'source': 'hacker-news.firebaseio.com',
                }
            )
        except Exception as e:
            logger.error(f"Failed to parse HN item: {e}")
            return None

    @staticmethod
    def _clean_title(title: str) -> str:
        """去掉 "Show HN: " 前缀，保留产品名本身"""
        for prefix in ('Show HN:', 'Show HN -', 'Show HN'):
            if title.startswith(prefix):
                return title[len(prefix):].strip(' :-') or title
        return title

    @staticmethod
    def _clean_text(raw: str) -> str:
        """正文是 HTML 片段，需剥离标签并还原 &#x27; 之类的实体"""
        if not raw:
            return ''
        text = BeautifulSoup(raw, 'html.parser').get_text(' ')
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _extract_tags(title: str, text: str) -> List[str]:
        """从标题和内容提取标签"""
        normalized = normalize_text(f"{title} {text}")
        tags = [
            tag for keyword, tag in TAG_KEYWORDS.items()
            if contains_keyword(normalized, keyword)
        ]
        return tags[:5]
