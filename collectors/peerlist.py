"""
Peerlist Launchpad 数据收集器（默认关闭）

Peerlist 是面向设计师与开发者的专业社交网络，其内置的 Launchpad 采用周更榜单，
对创始人的个人背景与技术实力展示更充分。

⚠️ 当前无法用本项目的采集方式获取：Launchpad 是纯客户端渲染（CSR）页面。
实测首页 HTML 只有约 44KB 的外壳，不含任何榜单数据；服务端也不返回 RSC 流式负载，
且公开 API 路径（/api/v1/launchpad、/api/v1/projects 等）全部 404。

因此本采集器不尝试伪造数据，而是直接抛出 CollectorError 说明原因与替代方案，
保持"采集不到就如实报告"的既有约定（见 main.py 对 CollectorError 的处理）。

若确实需要该数据源，可选路径：
1. 用带无头浏览器的采集器（如 Playwright）渲染后再解析 —— 会引入较重的依赖；
2. 让 AI Agent 用浏览器工具按需读取，而不是纳入定时批采集。
"""

import logging
from typing import Dict, List, Optional

from .base import BaseCollector, CollectorError, Product

logger = logging.getLogger(__name__)


class PeerlistCollector(BaseCollector):
    """Peerlist Launchpad 数据收集器"""

    def __init__(self, config):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://peerlist.io').rstrip('/')
        self.list_path = config.get('list_path', '/launchpad')

    def collect(self) -> List[Product]:
        raise CollectorError(
            'peerlist.io/launchpad 是纯客户端渲染页面，HTML 中不含榜单数据，'
            '且没有公开 API，因此无法用 HTTP 采集。'
            '如需该数据源，请改用带无头浏览器（Playwright）的采集方式，'
            '或保持 platforms.peerlist.enabled=false。'
        )

    def _parse_product(self, data: Dict) -> Optional[Product]:
        """无实际数据来源，保留接口以满足基类契约"""
        return None
