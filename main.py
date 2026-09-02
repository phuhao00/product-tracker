"""
Product Tracker 主程序
定期拉取产品发现平台数据并生成分析报告
"""

import argparse
import json
import logging
import logging.handlers
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# 允许从任意工作目录以脚本方式运行
sys.path.insert(0, str(Path(__file__).parent))

from analyzers import ProductAnalyzer, ReportGenerator
from collectors import CollectorError, Product, available_platforms, get_collector
from scheduler import Scheduler

__version__ = '1.1.0'

logger = logging.getLogger('product_tracker')

DATA_FILE_PATTERN = 'products_*.json'
REPORT_FILE_PATTERN = 'report_*'
# 归一化 URL 时剥离的跟踪参数
TRACKING_PARAM_RE = re.compile(r'[?&](utm_[^&=]*|ref|ref_src|source)=[^&]*')


@dataclass
class HistoryWindow:
    """趋势窗口内的历史数据"""
    products: List[Dict] = field(default_factory=list)
    # product_id -> {prev_votes, first_seen, appearances}
    product_stats: Dict[str, Dict] = field(default_factory=dict)
    snapshots: int = 0
    window_days: int = 7


def configure_logging(config: Dict, verbose: bool = False) -> None:
    """按配置初始化日志：控制台 + 滚动文件"""
    log_config = config.get('logging') or {}
    level = logging.DEBUG if verbose else getattr(
        logging, str(log_config.get('level', 'INFO')).upper(), logging.INFO
    )

    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Windows 控制台默认 GBK，输出 emoji / 中文会抛 UnicodeEncodeError 中断运行
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_path = Path(log_config.get('file') or './logs/tracker.log')
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=int(log_config.get('max_size_mb', 10)) * 1024 * 1024,
            backupCount=int(log_config.get('backup_count', 5)),
            encoding='utf-8',
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        root.warning(f"Could not open log file {log_path}: {e}")

    # 第三方库的调试日志过于嘈杂
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def load_config(config_path: str = None) -> Dict:
    """加载配置文件"""
    path = Path(config_path) if config_path else Path(__file__).parent / 'config.yaml'
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

    config.setdefault('app', {})
    config['app'].setdefault('data_dir', './data')
    config['app'].setdefault('reports_dir', './reports')
    return config


def normalize_url(url: str) -> str:
    """归一化 URL，用于跨平台识别同一产品"""
    if not url:
        return ''
    url = TRACKING_PARAM_RE.sub('', url.strip().lower())
    url = re.sub(r'^https?://', '', url)
    url = re.sub(r'^www\.', '', url)
    return url.rstrip('/?&#')


def normalize_name(name: str) -> str:
    """归一化产品名，用于跨平台识别同一产品"""
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())


class ProductTracker:
    """产品追踪器主类"""

    def __init__(self, config: Dict):
        self.config = config
        base_dir = Path(__file__).parent
        # 相对路径统一按项目根目录解析，避免受调用方工作目录影响
        self.data_dir = self._resolve(base_dir, config['app']['data_dir'])
        self.reports_dir = self._resolve(base_dir, config['app']['reports_dir'])

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self.analysis_config = config.get('analysis') or {}
        self.analyzer = ProductAnalyzer(self.analysis_config)
        self.report_generator = ReportGenerator({'reports_dir': str(self.reports_dir)})

        self.collectors = {}
        self.platform_status: Dict[str, str] = {}

    @staticmethod
    def _resolve(base_dir: Path, raw: str) -> Path:
        path = Path(raw)
        return path if path.is_absolute() else (base_dir / path).resolve()

    def init_collectors(self, only: Optional[List[str]] = None) -> None:
        """初始化各平台收集器"""
        platforms_config = self.config.get('platforms') or {}
        proxy_config = self.config.get('proxy') or {}
        proxies = {}
        if proxy_config.get('enabled'):
            proxies = {
                scheme: proxy_config[scheme]
                for scheme in ('http', 'https')
                if proxy_config.get(scheme)
            }

        for platform_name, platform_config in platforms_config.items():
            platform_config = dict(platform_config or {})

            if only and platform_name not in only:
                continue
            if not only and not platform_config.get('enabled', False):
                self.platform_status[platform_name] = 'disabled'
                continue

            if proxies:
                platform_config['proxies'] = proxies

            try:
                self.collectors[platform_name] = get_collector(platform_name, platform_config)
                self.platform_status[platform_name] = 'ready'
                logger.info(f"Initialized collector for {platform_name}")
            except Exception as e:
                self.platform_status[platform_name] = f'init failed: {e}'
                logger.error(f"Failed to initialize collector for {platform_name}: {e}")

        if only:
            unknown = set(only) - set(platforms_config)
            for name in unknown:
                logger.error(
                    f"Unknown platform '{name}'. Available: {available_platforms()}"
                )

    def collect_all(self) -> List[Product]:
        """从所有已启用平台收集数据"""
        all_products: List[Product] = []

        for platform_name, collector in self.collectors.items():
            logger.info(f"Collecting data from {platform_name}...")
            started = time.time()
            try:
                products = collector.collect()
            except CollectorError as e:
                self.platform_status[platform_name] = f'unavailable: {e}'
                logger.error(f"{platform_name} unavailable: {e}")
                continue
            except Exception as e:
                self.platform_status[platform_name] = f'failed: {e}'
                logger.exception(f"Failed to collect from {platform_name}: {e}")
                continue

            elapsed = time.time() - started
            self.platform_status[platform_name] = f'collected {len(products)} in {elapsed:.1f}s'
            logger.info(
                f"Collected {len(products)} products from {platform_name} ({elapsed:.1f}s)"
            )
            all_products.extend(products)

        merged = self.deduplicate(all_products)
        logger.info(
            f"Total collected: {len(all_products)} products "
            f"({len(merged)} after cross-platform dedup)"
        )
        return merged

    @staticmethod
    def deduplicate(products: List[Product]) -> List[Product]:
        """跨平台合并同一产品

        同一个产品常同时出现在多个榜单上。以目标 URL 为主键、
        产品名为辅键合并，保留热度最高的记录，其余平台记入 also_on。
        """
        index: Dict[str, Product] = {}
        merged: List[Product] = []

        for product in products:
            keys = []
            url_key = normalize_url(product.url)
            if url_key:
                keys.append(f"u:{url_key}")
            name_key = normalize_name(product.name)
            # 过短的名字（如 "AI"）撞名概率高，不作为合并依据
            if len(name_key) >= 4:
                keys.append(f"n:{name_key}")

            existing = next((index[k] for k in keys if k in index), None)

            if existing is None:
                for key in keys:
                    index[key] = product
                merged.append(product)
                continue

            also_on = existing.metadata.setdefault('also_on', [])
            if product.platform != existing.platform and product.platform not in also_on:
                also_on.append(product.platform)

            # 用热度更高的一条替换字段，但保留已累积的 also_on
            if product.votes > existing.votes:
                existing.votes = product.votes
                existing.comments = max(existing.comments, product.comments)
                if len(product.description) > len(existing.description):
                    existing.description = product.description
            for key in keys:
                index.setdefault(key, existing)

        return merged

    def load_history(self, exclude: Optional[Path] = None) -> HistoryWindow:
        """加载趋势窗口内的历史数据

        一次遍历同时得到两样东西：
        - products: 打平的历史产品列表，用于赛道占比与关键词的窗口对比
        - product_stats: 每个产品上一次的票数、窗口内首次出现时间与出现次数，
          用于计算单个产品的热度动量（"这个仓库比上次多了多少星"）
        """
        window_days = self.analysis_config.get('trend_window_days', 7)
        cutoff = time.time() - window_days * 86400
        window = HistoryWindow(window_days=window_days)
        # 按真实路径比较：若排除失败，本次快照会被当成自己的历史，
        # 导致所有动量恒为 0 且不报错
        excluded = exclude.resolve() if exclude else None

        # 文件名带时间戳，升序遍历后 prev_votes 自然停留在最近一次快照的值
        for path in sorted(self.data_dir.glob(DATA_FILE_PATTERN)):
            if excluded and path.resolve() == excluded:
                continue
            if path.stat().st_mtime < cutoff:
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Skipping unreadable history file {path.name}: {e}")
                continue

            products = payload.get('products') or []
            window.products.extend(products)
            window.snapshots += 1

            collected_at = payload.get('collected_at') or ''
            for product in products:
                product_id = product.get('id')
                if not product_id:
                    continue
                stats = window.product_stats.get(product_id)
                if stats is None:
                    window.product_stats[product_id] = {
                        'prev_votes': product.get('votes') or 0,
                        'first_seen': collected_at,
                        'appearances': 1,
                    }
                else:
                    stats['prev_votes'] = product.get('votes') or 0
                    stats['appearances'] += 1

        if window.snapshots:
            logger.info(
                f"Loaded {len(window.products)} historical products from "
                f"{window.snapshots} file(s) within {window_days} days "
                f"({len(window.product_stats)} distinct)"
            )
        return window

    def save_raw_data(self, products: List[Product]) -> Path:
        """保存原始数据"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = self.data_dir / f"products_{timestamp}.json"

        payload = {
            'collected_at': datetime.now().isoformat(timespec='seconds'),
            'version': __version__,
            'total': len(products),
            'platform_status': self.platform_status,
            'products': [p.to_dict() for p in products],
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        logger.info(f"Raw data saved to {filepath}")
        return filepath

    def analyze_and_report(
        self,
        products: List[Product],
        formats: List[str] = None,
        history: Optional[HistoryWindow] = None,
    ) -> List[str]:
        """分析数据并生成报告"""
        if not products:
            logger.warning("No products to analyze, skipping report generation")
            return []

        products_dict = [p.to_dict() for p in products]

        logger.info("Analyzing data...")
        analysis_result = self.analyzer.analyze(
            products_dict,
            history=history.products if history else None,
            product_stats=history.product_stats if history else None,
        )

        if formats is None:
            formats = self.analysis_config.get('report_formats') or ['html']

        report_paths = []
        for fmt in formats:
            try:
                report_paths.append(self.report_generator.generate(analysis_result, fmt))
            except Exception as e:
                logger.error(f"Failed to generate {fmt} report: {e}")

        return report_paths

    def cleanup_old_files(self) -> int:
        """按 retention_days 清理过期的数据与报告"""
        retention_days = self.analysis_config.get('retention_days', 90)
        if not retention_days:
            return 0

        cutoff = time.time() - retention_days * 86400
        removed = 0

        for directory, pattern in (
            (self.data_dir, DATA_FILE_PATTERN),
            (self.reports_dir, REPORT_FILE_PATTERN),
        ):
            for path in directory.glob(pattern):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    try:
                        path.unlink()
                        removed += 1
                    except OSError as e:
                        logger.warning(f"Could not delete {path.name}: {e}")

        if removed:
            logger.info(f"Cleaned up {removed} file(s) older than {retention_days} days")
        return removed

    def run_once(self, formats: List[str] = None) -> Tuple[List[Product], List[str]]:
        """执行一次完整的数据采集和分析"""
        logger.info("=" * 60)
        logger.info(f"Starting collection run (Product Tracker {__version__})")
        logger.info("=" * 60)
        started = time.time()

        products = self.collect_all()

        # 先读历史再写本次数据，避免把本次结果算进"历史"
        history = self.load_history()
        data_path = self.save_raw_data(products) if products else None
        report_paths = self.analyze_and_report(products, formats, history=history)
        self.cleanup_old_files()

        logger.info("=" * 60)
        logger.info(f"Run completed in {time.time() - started:.1f}s")
        logger.info(f"Products: {len(products)}")
        if data_path:
            logger.info(f"Raw data: {data_path}")
        for path in report_paths:
            logger.info(f"Report:   {path}")
        logger.info("=" * 60)

        return products, report_paths

    def run_scheduler(self, formats: List[str] = None):
        """启动定时任务"""
        scheduler_config = dict(self.config.get('scheduler') or {})
        if not scheduler_config.get('enabled', False):
            logger.warning("Scheduler is disabled in config (scheduler.enabled: false)")
            return

        scheduler = Scheduler(scheduler_config)
        scheduler.start(task=lambda: self.run_once(formats))

    def close(self):
        for collector in self.collectors.values():
            collector.close()


def cmd_run(tracker: ProductTracker, args) -> int:
    tracker.init_collectors(only=args.platform)
    if not tracker.collectors:
        logger.error("No collectors enabled. Check config.yaml or use --platform.")
        return 1

    products, reports = tracker.run_once(args.format)
    if not products:
        logger.error("Collection produced no products.")
        return 1

    if args.open and reports:
        _open_report(reports)
    return 0


def cmd_schedule(tracker: ProductTracker, args) -> int:
    tracker.init_collectors(only=args.platform)
    if not tracker.collectors:
        logger.error("No collectors enabled. Check config.yaml or use --platform.")
        return 1

    if args.once:
        products, _ = tracker.run_once(args.format)
        return 0 if products else 1

    tracker.run_scheduler(args.format)
    return 0


def cmd_report(tracker: ProductTracker, args) -> int:
    """从已有的原始数据重新生成报告，不重新联网采集"""
    files = sorted(tracker.data_dir.glob(DATA_FILE_PATTERN))
    if not files:
        logger.error(f"No collected data found in {tracker.data_dir}. Run 'run' first.")
        return 1

    latest = files[-1]
    logger.info(f"Regenerating report from {latest.name}")
    with open(latest, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    products = payload.get('products') or []
    if not products:
        logger.error(f"{latest.name} contains no products")
        return 1

    history = tracker.load_history(exclude=latest)
    result = tracker.analyzer.analyze(
        products, history=history.products, product_stats=history.product_stats
    )

    reports = []
    for fmt in (args.format or ['html']):
        try:
            reports.append(tracker.report_generator.generate(result, fmt))
        except Exception as e:
            logger.error(f"Failed to generate {fmt} report: {e}")

    for path in reports:
        logger.info(f"Report: {path}")

    if args.open and reports:
        _open_report(reports)
    return 0 if reports else 1


def cmd_config(tracker: ProductTracker, args) -> int:
    print(json.dumps(tracker.config, indent=2, ensure_ascii=False))
    return 0


def cmd_status(tracker: ProductTracker, args) -> int:
    tracker.init_collectors(only=args.platform)
    platforms_config = tracker.config.get('platforms') or {}

    print(f"\nProduct Tracker {__version__}")
    print("=" * 60)
    print(f"  Data dir:    {tracker.data_dir}")
    print(f"  Reports dir: {tracker.reports_dir}")

    print(f"\n  Platforms ({len(tracker.collectors)} enabled / {len(platforms_config)} configured):")
    for name in sorted(platforms_config):
        enabled = (platforms_config[name] or {}).get('enabled', False)
        mark = 'on ' if name in tracker.collectors else ('off' if not enabled else '!! ')
        print(f"    [{mark}] {name}")

    scheduler_config = tracker.config.get('scheduler') or {}
    if scheduler_config.get('use_cron') and scheduler_config.get('cron_expression'):
        schedule_desc = f"cron '{scheduler_config['cron_expression']}'"
    else:
        schedule_desc = f"every {scheduler_config.get('interval_minutes', 1440)} min"
    print(f"\n  Scheduler:   {'enabled' if scheduler_config.get('enabled') else 'disabled'}"
          f" ({schedule_desc})")

    data_files = sorted(tracker.data_dir.glob(DATA_FILE_PATTERN))
    print(f"\n  Collected data files: {len(data_files)}")
    if data_files:
        latest = data_files[-1]
        modified = datetime.fromtimestamp(latest.stat().st_mtime)
        age = datetime.now() - modified
        print(f"    Latest: {latest.name} ({_humanize(age)} ago)")

    reports = sorted(tracker.reports_dir.glob(REPORT_FILE_PATTERN), reverse=True)
    print(f"\n  Reports: {len(reports)}")
    for report in reports[:5]:
        print(f"    - {report.name}")
    if not reports:
        print("    (none yet — run 'python main.py run')")

    print()
    return 0


def cmd_clean(tracker: ProductTracker, args) -> int:
    removed = tracker.cleanup_old_files()
    retention = tracker.analysis_config.get('retention_days', 90)
    print(f"Removed {removed} file(s) older than {retention} days")
    return 0


def _humanize(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _open_report(reports: List[str]) -> None:
    """在默认浏览器中打开 HTML 报告"""
    import webbrowser

    target = next((r for r in reports if r.endswith('.html')), reports[0])
    logger.info(f"Opening {target}")
    webbrowser.open(Path(target).resolve().as_uri())


COMMANDS = {
    'run': cmd_run,
    'schedule': cmd_schedule,
    'report': cmd_report,
    'config': cmd_config,
    'status': cmd_status,
    'clean': cmd_clean,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='main.py',
        description='Product Tracker - 产品发现平台数据追踪器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
命令:
  run       采集数据、分析并生成报告
  schedule  按 config.yaml 的计划持续运行
  report    用最近一次已采集的数据重新生成报告（不联网）
  config    打印当前生效配置
  status    显示平台开关、调度设置与历史产物
  clean     按 retention_days 清理过期数据与报告

示例:
  python main.py run --format html markdown --open
  python main.py run --platform hackernews github_trending
  python main.py schedule
  python main.py report --format html
        """
    )

    parser.add_argument('command', choices=sorted(COMMANDS), help='执行的命令')
    parser.add_argument('--config', '-c', default=None, help='配置文件路径 (默认: config.yaml)')
    parser.add_argument(
        '--format', '-f',
        nargs='+',
        choices=['html', 'json', 'markdown'],
        default=None,
        help='报告格式，可多选 (默认取 config.yaml 的 report_formats)'
    )
    parser.add_argument(
        '--platform', '-p',
        nargs='+',
        default=None,
        metavar='NAME',
        help=f"只采集指定平台，忽略 enabled 开关。可选: {', '.join(available_platforms())}"
    )
    parser.add_argument('--once', action='store_true', help='schedule 命令下只执行一次')
    parser.add_argument('--open', action='store_true', help='生成后在浏览器中打开 HTML 报告')
    parser.add_argument('--verbose', '-v', action='store_true', help='输出调试日志')
    parser.add_argument('--version', action='version', version=f'Product Tracker {__version__}')
    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"Failed to load config: {e}", file=sys.stderr)
        return 2

    configure_logging(config, verbose=args.verbose)

    tracker = ProductTracker(config)
    try:
        return COMMANDS[args.command](tracker, args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    finally:
        tracker.close()


if __name__ == '__main__':
    sys.exit(main())
