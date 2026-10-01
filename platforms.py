"""
平台元信息
供采集、分析与报告模块共享，避免各处重复维护平台名映射
"""

PLATFORM_LABELS = {
    # 打榜与每日精选
    'producthunt': 'Product Hunt',
    'fazier': 'Fazier',
    'uneed': 'Uneed',
    'microlaunch': 'MicroLaunch',
    'peerlist': 'Peerlist Launchpad',
    'startupage': 'StartuPage',
    # 早期 / 内测阶段
    'betalist': 'BetaList',
    'betabound': 'Betabound',
    # 开发者与技术社区
    'hackernews': 'Hacker News',
    'devhunt': 'DevHunt',
    'github_trending': 'GitHub Trending',
    # 独立创作者社区与国内平台
    'indiehackers': 'Indie Hackers',
    'xinquji': '新趣集',
}

# 平台分组：报告里按"打榜 / 早期 / 开发者 / 社区"归类展示，
# 也方便看出某个赛道是被哪一类平台带热的。
PLATFORM_GROUPS = {
    'launch': ('producthunt', 'fazier', 'uneed', 'microlaunch', 'peerlist', 'startupage'),
    'early': ('betalist', 'betabound'),
    'developer': ('hackernews', 'devhunt', 'github_trending'),
    'community': ('indiehackers', 'xinquji'),
}

GROUP_LABELS = {
    'launch': '打榜与每日精选',
    'early': '早期与内测',
    'developer': '开发者与技术',
    'community': '创作者社区与国内',
}


# 各平台"热度"字段的实际含义。不同平台量级不可直接比较，
# 报告中需按平台内百分位归一化，并把口径明确告诉读者。
HEAT_BASIS = {
    'hackernews': '得票数',
    'github_trending': '周期内新增星数',
    'producthunt': '得票数（官方 embed 徽章）',
    'fazier': '得票数',
    'indiehackers': 'Stripe 验证月收入（MRR）',
    'startupage': 'Stripe 验证月收入（MRR）',
    'betalist': '列表顺序',
    'betabound': '列表顺序',
    'devhunt': '榜单排名',
    'xinquji': '列表顺序',
    'uneed': '列表顺序',
    'microlaunch': '列表顺序',
    'peerlist': '榜单排名',
}

# 无公开热度数据时退化为列表顺序
POSITION_BASIS = '列表顺序（该平台无公开热度数据）'


def platform_label(platform: str) -> str:
    """返回平台的展示名，未知平台原样返回"""
    return PLATFORM_LABELS.get(platform, platform or 'unknown')


def platform_group(platform: str) -> str:
    """返回平台所属分组 key，未知平台归入 community"""
    for group, members in PLATFORM_GROUPS.items():
        if platform in members:
            return group
    return 'community'


def heat_basis(platform: str, has_votes: bool) -> str:
    """返回该平台热度分的计算口径说明"""
    if not has_votes:
        return POSITION_BASIS
    return HEAT_BASIS.get(platform, '平台热度值')
