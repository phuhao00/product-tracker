"""
Uneed 数据收集器（默认关闭）

海外公认目前最火的 Product Hunt 替代品之一：极简、公平的打榜环境，每日更新，
对独立开发者与 AI 工具特别友好。

⚠️ 当前不可用：本站整站由 Cloudflare Bot Management 保护，对非浏览器客户端
（requests / curl，即便补齐完整的浏览器请求头）恒返回 403，且没有公开 API。
实测的各个候选入口（/rss、/feed、/launches、/api/*、/sitemap.xml）全部 403。

启用方式：在 config.yaml 的 proxy 段配置一个出口稳定的代理（住宅代理通常可过），
再把 platforms.uneed.enabled 置为 true。解析规则尚未用真实页面验证，
首次启用请用 `python main.py run -p uneed -v` 检查解析结果。
"""

import logging
import re

from .blocked import WafBlockedCollector

logger = logging.getLogger(__name__)

# 站点路径结构无法取样，这里覆盖几种常见的产品详情页形态
PRODUCT_LINK_RE = re.compile(
    r'^/(?:tool|tools|launch|launches|p|product|products)/([^/?#]+)/?$'
)


class UneedCollector(WafBlockedCollector):
    """Uneed 数据收集器"""

    HOME_PATH = '/'
    PRODUCT_LINK_RE = PRODUCT_LINK_RE
    LINK_TEMPLATE = '{base}/tool/{slug}'

    def __init__(self, config):
        super().__init__(config)
        self.base_url = config.get('base_url', 'https://www.uneed.best').rstrip('/')
