"""
MicroLaunch 数据收集器（默认关闭）

专为微型 SaaS（Micro-SaaS）与个人开发者项目量身定做的发布平台。
它的曝光周期长达一个月，适合不需要短期流量暴增、而要持续打磨 MVP 的项目。

⚠️ 当前不可用：本站整站由 Cloudflare Bot Management 保护，对非浏览器客户端
恒返回 403，且没有公开 API。实测 /rss、/feed、/api/products、/sitemap.xml 全部 403。

启用方式：在 config.yaml 的 proxy 段配置一个出口稳定的代理后再启用。
解析规则尚未用真实页面验证，首次启用请用 `python main.py run -p microlaunch -v` 检查。
"""

import logging
import re

from .blocked import WafBlockedCollector

logger = logging.getLogger(__name__)

PRODUCT_LINK_RE = re.compile(
    r'^/(?:p|product|products|startup|startups|project|projects)/([^/?#]+)/?$'
)


class MicroLaunchCollector(WafBlockedCollector):
    """MicroLaunch 数据收集器"""

    HOME_PATH = '/'
    PRODUCT_LINK_RE = PRODUCT_LINK_RE
    LINK_TEMPLATE = '{base}/p/{slug}'

    def __init__(self, config):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://microlaunch.net').rstrip('/')
