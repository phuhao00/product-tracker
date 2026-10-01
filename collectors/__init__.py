"""
数据收集器模块
支持多个产品发现平台
"""

from typing import Dict, List

from .base import BaseCollector, CollectorError, Product
from .betabound import BetaBoundCollector
from .betalist import BetaListCollector
from .devhunt import DevHuntCollector
from .fazier import FazierCollector
from .github_trending import GitHubTrendingCollector
from .hackernews import HackerNewsCollector
from .indiehackers import IndieHackersCollector
from .microlaunch import MicroLaunchCollector
from .peerlist import PeerlistCollector
from .producthunt import ProductHuntCollector
from .startupage import StartuPageCollector
from .uneed import UneedCollector
from .xinquji import XinqujiCollector

COLLECTORS = {
    # 打榜与每日精选
    'producthunt': ProductHuntCollector,
    'fazier': FazierCollector,
    'uneed': UneedCollector,
    'microlaunch': MicroLaunchCollector,
    'peerlist': PeerlistCollector,
    'startupage': StartuPageCollector,
    # 早期 / 内测阶段
    'betalist': BetaListCollector,
    'betabound': BetaBoundCollector,
    # 开发者与技术社区
    'hackernews': HackerNewsCollector,
    'devhunt': DevHuntCollector,
    'github_trending': GitHubTrendingCollector,
    # 独立创作者社区与国内平台
    'indiehackers': IndieHackersCollector,
    'xinquji': XinqujiCollector,
}

__all__ = [
    'BaseCollector',
    'CollectorError',
    'Product',
    'ProductHuntCollector',
    'FazierCollector',
    'UneedCollector',
    'MicroLaunchCollector',
    'PeerlistCollector',
    'StartuPageCollector',
    'BetaListCollector',
    'BetaBoundCollector',
    'HackerNewsCollector',
    'DevHuntCollector',
    'GitHubTrendingCollector',
    'IndieHackersCollector',
    'XinqujiCollector',
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

    # 采集器自报家门时要用到配置里的键名（如 uneed），而不是展示名（如 Uneed）
    config.setdefault('_platform_key', platform)
    return collector_class(config)
