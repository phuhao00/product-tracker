"""
RSS / Atom 订阅源解析

多个采集器（新趣集、Betabound）只提供订阅源而不开放 API，
这里把 RSS 2.0 与 Atom 统一成同一种字段字典，避免每个采集器各写一遍。
"""

import logging
from typing import Dict, List, Optional
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

NAMESPACES = {
    'dc': 'http://purl.org/dc/elements/1.1/',
    'content': 'http://purl.org/rss/1.0/modules/content/',
    'atom': 'http://www.w3.org/2005/Atom',
}


def parse_feed(root: ElementTree.Element) -> List[Dict[str, str]]:
    """把 RSS 2.0 / Atom 文档统一成条目字典列表

    返回字段：title / link / description / published / author / categories
    """
    if root is None:
        return []

    # Atom 用 <entry>，RSS 用 <item>；带上命名空间再兜一遍
    items = root.findall('.//item') or root.findall('.//atom:entry', NAMESPACES)
    return [entry for entry in (_parse_entry(item) for item in items) if entry]


def _parse_entry(item: ElementTree.Element) -> Optional[Dict[str, str]]:
    """解析单个条目，缺标题的条目直接丢弃"""
    title = _text(item, 'title')
    if not title:
        return None

    return {
        'title': title,
        'link': _link(item),
        'description': _description(item),
        'published': _published(item),
        'author': _author(item),
        'categories': _categories(item),
    }


def _text(item: ElementTree.Element, tag: str) -> str:
    child = item.find(tag)
    if child is None:
        child = item.find(f'atom:{tag}', NAMESPACES)
    if child is None or child.text is None:
        return ''
    return child.text.strip()


def _link(item: ElementTree.Element) -> str:
    """RSS 的 <link> 是文本，Atom 的 <link> 是 href 属性"""
    link = _text(item, 'link')
    if link:
        return link

    for child in item.findall('atom:link', NAMESPACES):
        rel = child.get('rel', 'alternate')
        if rel == 'alternate' and child.get('href'):
            return child.get('href', '').strip()
    return ''


def _description(item: ElementTree.Element) -> str:
    """优先取完整正文（content:encoded），否则退到 description/summary"""
    for tag in ('content:encoded', 'description', 'summary'):
        value = _text(item, tag) if ':' not in tag else _namespaced_text(item, tag)
        if value:
            return value
    return ''


def _namespaced_text(item: ElementTree.Element, tag: str) -> str:
    prefix, _, local = tag.partition(':')
    uri = NAMESPACES.get(prefix)
    if not uri:
        return ''
    child = item.find(f'{{{uri}}}{local}')
    if child is None or child.text is None:
        return ''
    return child.text.strip()


def _published(item: ElementTree.Element) -> str:
    for tag in ('pubDate', 'published', 'updated'):
        value = _text(item, tag)
        if value:
            return value
    return ''


def _author(item: ElementTree.Element) -> str:
    for tag in ('creator', 'author'):
        value = _namespaced_text(item, f'dc:{tag}') or _text(item, tag)
        if value:
            return value
    return ''


def _categories(item: ElementTree.Element) -> List[str]:
    values = []
    for child in item.findall('category'):
        if child.text:
            values.append(child.text.strip())
    return values
