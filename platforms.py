"""
平台元信息
供采集、分析与报告模块共享，避免各处重复维护平台名映射
"""

PLATFORM_LABELS = {
    'producthunt': 'Product Hunt',
    'hackernews': 'Hacker News',
    'betalist': 'BetaList',
    'devhunt': 'DevHunt',
    'github_trending': 'GitHub Trending',
}


# 各平台"热度"字段的实际含义。不同平台量级不可直接比较，
# 报告中需按平台内百分位归一化，并把口径明确告诉读者。
HEAT_BASIS = {
    'hackernews': '得票数',
    'github_trending': '周期内新增星数',
    'producthunt': 'feed 排序',
    'betalist': '列表顺序',
    'devhunt': '榜单排名',
}

# 无公开热度数据时退化为列表顺序
POSITION_BASIS = '列表顺序（该平台无公开热度数据）'


def platform_label(platform: str) -> str:
    """返回平台的展示名，未知平台原样返回"""
    return PLATFORM_LABELS.get(platform, platform or 'unknown')


def heat_basis(platform: str, has_votes: bool) -> str:
    """返回该平台热度分的计算口径说明"""
    if not has_votes:
        return POSITION_BASIS
    return HEAT_BASIS.get(platform, '平台热度值')
