"""
数据收集器模块
支持多个产品发现平台
"""

from typing import Dict, List

from .base import BaseCollector, CollectorError, Product
from .betalist import BetaListCollector
from .devhunt import DevHuntCollector
from .github_trending import GitHubTrendingCollector
from .hackernews import HackerNewsCollector
from .producthunt import ProductHuntCollector

COLLECTORS = {
    'producthunt': ProductHuntCollector,
    'hackernews': HackerNewsCollector,
    'betalist': BetaListCollector,
    'devhunt': DevHuntCollector,
    'github_trending': GitHubTrendingCollector,
}

__all__ = [
    'BaseCollector',
    'CollectorError',
    'Product',
    'ProductHuntCollector',
    'HackerNewsCollector',
    'BetaListCollector',
    'DevHuntCollector',
    'GitHubTrendingCollector',
    'COLLECTORS',
    'get_collector',
    'available_platforms',
]


def available_platforms() -> List[str]:
    """返回所有已注册的平台名"""
    return sorted(COLLECTORS)


def get_collector(platform: str, config: Dict) -> BaseCollector:
    """获取指定平台的收集器实例"""
    collector_class = COLLECTORS.get(platform)
    if not collector_class:
        raise ValueError(
            f"Unknown platform: {platform}. Available: {available_platforms()}"
        )

    return collector_class(config)
