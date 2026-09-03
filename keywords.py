"""
关键词匹配工具

朴素的子串匹配会产生大量误报（"AI" 命中 available/email/maintain，
"go" 命中 google/going），因此单词类关键词一律按词边界匹配，
并在匹配前把连字符等分隔符归一化，让 "open-source" 能命中 "open source"。
"""

import re
from functools import lru_cache
from typing import Iterable, List

# 连字符、下划线、斜杠等在英文标题里等价于空格
SEPARATOR_RE = re.compile(r'[-_/\\|,.:;()\[\]{}"\']+')
WHITESPACE_RE = re.compile(r'\s+')


def normalize_text(text: str) -> str:
    """归一化待匹配文本：小写、分隔符转空格、折叠空白

    顺带拆开 camelCase / 字母数字边界（HydraDB → hydra db，GPT4 → gpt 4），
    否则后缀类关键词（db、llm）永远匹配不到粘写的产品名。
    """
    if not text:
        return ''
    spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    spaced = re.sub(r'([A-Za-z])([0-9])', r'\1 \2', spaced)
    spaced = re.sub(r'([0-9])([A-Za-z])', r'\1 \2', spaced)
    lowered = SEPARATOR_RE.sub(' ', spaced.lower())
    return f" {WHITESPACE_RE.sub(' ', lowered).strip()} "


# 允许匹配复数的最短词长。太短的词加复数后缀会误伤（go → goes）
MIN_PLURAL_LENGTH = 3


@lru_cache(maxsize=1024)
def _keyword_pattern(keyword: str) -> re.Pattern:
    normalized = normalize_text(keyword).strip()
    # 关键词末词允许 s/es 复数形式，否则 "language model" 匹配不到 "language models"
    last_word = normalized.rsplit(' ', 1)[-1]
    plural = r'(?:es|s)?' if len(last_word) >= MIN_PLURAL_LENGTH else ''
    # 多词关键词已被归一化为单空格分隔，整体按词边界匹配
    return re.compile(rf'(?<![a-z0-9]){re.escape(normalized)}{plural}(?![a-z0-9])')


def contains_keyword(normalized_text: str, keyword: str) -> bool:
    """判断归一化文本中是否包含关键词（按词边界）"""
    if not normalized_text or not keyword:
        return False
    return bool(_keyword_pattern(keyword).search(normalized_text))


def match_keywords(text: str, keywords: Iterable[str]) -> List[str]:
    """返回文本中命中的关键词列表，保持给定顺序"""
    normalized = normalize_text(text)
    return [kw for kw in keywords if contains_keyword(normalized, kw)]
