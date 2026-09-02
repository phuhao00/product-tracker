"""
基础数据收集器类
所有平台收集器的基类
"""

import abc
import json
import logging
import random
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

# 触发重试的响应码：限流与服务端临时故障
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class CollectorError(Exception):
    """收集器无法完成采集（数据源不可用、结构变更等）"""


@dataclass
class Product:
    """产品数据模型"""
    id: str
    name: str
    description: str
    url: str
    platform: str
    votes: int = 0
    comments: int = 0
    category: str = ""
    tags: List[str] = field(default_factory=list)
    author: str = ""
    image: str = ""
    created_at: str = ""
    collected_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.collected_at:
            self.collected_at = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return asdict(self)


class BaseCollector(abc.ABC):
    """数据收集器基类"""

    def __init__(self, config: Dict):
        self.config = config
        self.platform_name = config.get('name', 'unknown')
        self.rate_limit = config.get('rate_limit', 5)
        self.max_items = config.get('max_items', 50)
        self.timeout = config.get('timeout', 30)
        self.max_retries = config.get('max_retries', 3)
        self.last_request_time = 0.0

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': config.get('user_agent', DEFAULT_USER_AGENT),
            'Accept-Language': 'en-US,en;q=0.9',
        })

        proxies = config.get('proxies') or {}
        if proxies:
            self.session.proxies.update(proxies)
            logger.debug(f"{self.platform_name}: using proxy {proxies}")

    @abc.abstractmethod
    def collect(self) -> List[Product]:
        """收集产品数据，子类必须实现"""

    @abc.abstractmethod
    def _parse_product(self, data: Dict) -> Optional[Product]:
        """解析单个产品数据，子类必须实现"""

    def close(self):
        self.session.close()

    def _respect_rate_limit(self):
        """遵守速率限制"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit:
            sleep_time = self.rate_limit - elapsed
            logger.debug(f"Rate limit: sleeping for {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _fetch(self, url: str, headers: Dict = None) -> Optional[requests.Response]:
        """带重试与退避的 HTTP 请求，返回 None 表示最终失败"""
        for attempt in range(1, self.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = self.session.get(url, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                logger.warning(f"Request error ({attempt}/{self.max_retries}) {url}: {e}")
            else:
                if response.status_code not in RETRYABLE_STATUS:
                    if response.ok:
                        return response
                    logger.error(f"Request failed [{response.status_code}] {url}")
                    return None
                logger.warning(
                    f"Retryable status {response.status_code} "
                    f"({attempt}/{self.max_retries}) {url}"
                )

            if attempt < self.max_retries:
                # 指数退避 + 抖动，避免多个收集器同步重试
                backoff = min(2 ** attempt + random.uniform(0, 1), 30)
                logger.debug(f"Backing off {backoff:.1f}s before retry")
                time.sleep(backoff)

        logger.error(f"Giving up after {self.max_retries} attempts: {url}")
        return None

    def _make_request(self, url: str, headers: Dict = None) -> Optional[str]:
        """获取文本响应"""
        response = self._fetch(url, headers)
        return response.text if response else None

    def _make_json_request(self, url: str, headers: Dict = None) -> Optional[Any]:
        """获取JSON响应"""
        merged = {'Accept': 'application/json'}
        if headers:
            merged.update(headers)

        response = self._fetch(url, merged)
        if not response:
            return None
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"JSON decode failed for {url}: {e}")
            return None

    def _make_xml_request(self, url: str, headers: Dict = None) -> Optional[ElementTree.Element]:
        """获取并解析XML/Atom响应"""
        merged = {'Accept': 'application/atom+xml, application/rss+xml, application/xml'}
        if headers:
            merged.update(headers)

        response = self._fetch(url, merged)
        if not response:
            return None
        try:
            # 用 bytes 解析，交由声明的编码决定，避免 requests 猜错编码
            return ElementTree.fromstring(response.content)
        except ElementTree.ParseError as e:
            logger.error(f"XML parse failed for {url}: {e}")
            return None

    @staticmethod
    def _dedupe(products: List[Product]) -> List[Product]:
        """按 id 去重，保留首次出现的顺序"""
        seen = set()
        unique = []
        for p in products:
            if p.id not in seen:
                seen.add(p.id)
                unique.append(p)
        return unique

    def save_data(self, products: List[Product], filepath: str):
        """保存数据到JSON文件"""
        data = {
            'platform': self.platform_name,
            'collected_at': datetime.now().isoformat(),
            'count': len(products),
            'products': [p.to_dict() for p in products]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(products)} products to {filepath}")
