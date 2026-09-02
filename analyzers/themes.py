"""
赛道（主题）分类

单个产品刷过去很难判断趋势，趋势的载体是赛道。这里用规则把产品归入赛道，
使报告能在赛道层面做跨平台聚合与环比对比，作为决策单元。

两条设计要点：
1. 标题比正文更能代表产品，因此按位置加权（标题 > 标签 > 正文）。
   否则正文里一句"a silly alternative to LinkedIn Games"就会把一个解谜游戏
   判成"开源替代品"。
2. 多词关键词更具体，命中权重翻倍。

THEME_DEFINITIONS 的顺序即同分时的优先级，越靠前越具体。
"""

from typing import Dict, List, Tuple

from keywords import contains_keyword, normalize_text

OTHER_THEME = ('other', '其他')

# 命中位置的权重：标题是产品的自我定位，最可信
ZONE_WEIGHTS = (('name', 3), ('tags', 2), ('description', 1))

# (key, 展示名, 关键词)
THEME_DEFINITIONS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ('ai_agent', 'AI 智能体', (
        'agent', 'agentic', 'multi agent', 'sub agent', 'autonomous', 'copilot',
        'mcp', 'claude code', 'agent skill', 'ai assistant', 'ai advisory',
        'ai teleprompter', 'chatbot',
    )),
    # 不收录 claude / openai 这类厂商名：它们标示生态而非领域，
    # "claude-mem"（给智能体做记忆）会被误判成模型类产品。
    ('llm', 'LLM 与模型', (
        'llm', 'gpt', 'rag', 'embedding', 'vector search', 'fine tune',
        'prompt', 'inference', 'language model', 'foundation model',
        'ai model', 'diffusion', 'quantization',
    )),
    ('oss_alt', '开源替代品', (
        'alternative', 'alternative to', 'open source alternative',
        'self hosted', 'drop in replacement', 'local first', 'clone',
        'ported', 'port of', 'reimplementation',
    )),
    # 注意：不要把 "open source" 之类的许可证/分发属性放进任何赛道。
    # 它描述的是产品怎么发布，而不是产品做什么，且部分采集器会给每条记录都打该标签。
    ('devtools', '开发者工具', (
        'cli', 'sdk', 'api', 'ide', 'terminal', 'debugger', 'compiler',
        'linter', 'framework', 'devtools', 'developer tool', 'code editor',
        'boilerplate', 'plugin', 'extension', 'markdown', 'syntax highlighting',
        'code review', 'code generation', 'git', 'react', 'vue', 'tailwind',
        'typescript', 'rust', 'elixir', 'golang', 'webassembly',
    )),
    ('infra', '基础设施与运维', (
        'kubernetes', 'docker', 'deploy', 'hosting', 'serverless', 'database',
        'sql', 'cache', 'proxy', 'devops', 'ci cd', 'monitoring',
        'observability', 'container', 'load balancer', 'infrastructure',
        'linux', 'server', 'ssh', 'distro', 'uptime', 'gpu compute',
        'proxies', 'self host',
    )),
    ('data', '数据与分析', (
        'analytics', 'dashboard', 'etl', 'data pipeline', 'visualization',
        'spreadsheet', 'excel', 'chart', 'metrics', 'data warehouse',
        'scraper', 'crawler', 'dataset', 'search engine', 'benchmark',
    )),
    ('security', '安全与隐私', (
        'security', 'privacy', 'encryption', 'zero knowledge', 'vpn',
        'password', 'vulnerability', 'compliance', 'firewall', 'redacted',
        'censorship', 'authentication', 'malware', 'phishing',
    )),
    ('fintech', '金融与支付', (
        'payment', 'invoice', 'billing', 'fintech', 'crypto', 'wallet',
        'accounting', 'tax', 'subscription', 'pricing', 'finance', 'trading',
        'price index', 'revenue', 'budget',
    )),
    ('growth', '营销与增长', (
        'seo', 'ads', 'marketing', 'growth', 'newsletter', 'email campaign',
        'social media', 'landing page', 'advertising', 'copywriting',
        'lead generation', 'sales', 'sales pipeline', 'brand', 'ad space',
        'search bot', 'client approval', 'waitlist',
    )),
    ('career', '招聘与职业', (
        'job', 'resume', 'hiring', 'recruit', 'career', 'interview', 'ats',
        'freelance', 'portfolio', 'cover letter', 'visa',
    )),
    ('education', '教育与学习', (
        'learn', 'learning', 'course', 'education', 'study', 'tutor', 'quiz',
        'flashcard', 'teach', 'classroom', 'research', 'speaking',
        'pronunciation', 'language learning', 'mentor', 'coach', 'practice',
        'curriculum',
    )),
    ('game', '游戏与娱乐', (
        'game', 'puzzle', 'word game', 'arcade', 'trivia', 'rpg', 'sudoku',
        'crossword', 'word ladder', 'leaderboard',
    )),
    ('content', '内容与阅读', (
        'read later', 'e reader', 'ereader', 'ebook', 'book', 'manga',
        'comic', 'podcast', 'digest', 'rss', 'reading', 'wikipedia',
        'article', 'blog', 'newsroom', 'transcript', 'summarize',
        'media library', 'streaming', 'tv',
    )),
    ('creative', '设计与创意', (
        'design', 'video', 'image', 'photo', 'animation', 'font', 'ui kit',
        'illustration', 'render', '3d', 'audio', 'music', 'synth', 'sampler',
        'drum machine', 'microphone', 'mic', 'video editor', 'photo editor',
        'screen recording', 'teleprompter', 'screenshot', 'wallpaper', 'voice',
    )),
    ('productivity', '生产力与协作', (
        'productivity', 'notes', 'note taking', 'docs', 'calendar', 'task',
        'todo', 'project management', 'workflow', 'automation', 'crm',
        'meeting', 'knowledge base', 'collaboration', 'planner', 'scheduling',
        'time tracking', 'shift', 'checklist', 'reminder',
    )),
    ('hardware', '硬件与设备', (
        'gimbal', 'robot', 'iot', 'sensor', 'camera', '3d print', 'slicer',
        'macbook', 'notch', 'e ink', 'hardware', 'firmware', 'raspberry pi',
        'wearable', 'drone',
    )),
    ('legal', '法务与合规', (
        'patent', 'legal', 'contract', 'trademark', 'copyright', 'regulation',
        'gdpr', 'lawyer',
    )),
    ('lifestyle', '健康与生活', (
        'health', 'fitness', 'sleep', 'food', 'recipe', 'travel', 'habit',
        'meditation', 'workout', 'nutrition', 'wardrobe', 'hobby', 'family',
        'air quality', 'pollution', 'exercise', 'athlete', 'dating',
        'mental health', 'parenting',
    )),
]

THEME_LABELS: Dict[str, str] = {key: label for key, label, _ in THEME_DEFINITIONS}
THEME_LABELS[OTHER_THEME[0]] = OTHER_THEME[1]

THEME_ORDER: List[str] = [key for key, _, _ in THEME_DEFINITIONS] + [OTHER_THEME[0]]

_THEME_INDEX = {key: i for i, key in enumerate(THEME_ORDER)}


def theme_label(key: str) -> str:
    return THEME_LABELS.get(key, key)


def score_themes(name: str, description: str = '', tags: List[str] = None) -> Dict[str, int]:
    """返回各赛道的加权命中得分

    命中权重 = 位置权重（标题 3 / 标签 2 / 正文 1）× 关键词具体度（多词 2 / 单词 1）
    """
    zones = {
        'name': normalize_text(name),
        'tags': normalize_text(' '.join(tags or [])),
        'description': normalize_text(description),
    }
    if not any(zone.strip() for zone in zones.values()):
        return {}

    scores: Dict[str, int] = {}
    for key, _, terms in THEME_DEFINITIONS:
        score = 0
        for term in terms:
            specificity = 2 if ' ' in term else 1
            for zone, weight in ZONE_WEIGHTS:
                if zones[zone] and contains_keyword(zones[zone], term):
                    score += weight * specificity
        if score:
            scores[key] = score
    return scores


def classify(name: str, description: str = '', tags: List[str] = None) -> Tuple[str, List[str]]:
    """判定产品的主赛道与全部命中赛道

    返回 (主赛道 key, 命中赛道 key 列表)。命中列表按得分降序，
    得分相同时按 THEME_DEFINITIONS 的顺序（越具体越靠前）。
    """
    scores = score_themes(name, description, tags)
    if not scores:
        return OTHER_THEME[0], [OTHER_THEME[0]]

    ranked = sorted(scores, key=lambda k: (-scores[k], _THEME_INDEX[k]))
    return ranked[0], ranked
