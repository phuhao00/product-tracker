"""
定时任务调度器
支持按固定间隔或 cron 表达式周期性执行数据采集任务
"""

import logging
import signal
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# cron 字段范围：分 时 日 月 周
CRON_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
CRON_FIELD_NAMES = ('minute', 'hour', 'day', 'month', 'weekday')


class CronExpression:
    """最小 cron 表达式实现

    支持标准 5 字段格式与 `*`、`*/n`、`a-b`、`a,b,c` 组合。
    不支持 `L`、`#`、`?` 等扩展语法。
    """

    def __init__(self, expression: str):
        self.expression = expression.strip()
        fields = self.expression.split()
        if len(fields) != 5:
            raise ValueError(
                f"Invalid cron expression '{expression}': expected 5 fields, got {len(fields)}"
            )

        self.fields: List[Set[int]] = [
            self._parse_field(value, low, high, name)
            for value, (low, high), name in zip(fields, CRON_FIELD_RANGES, CRON_FIELD_NAMES)
        ]

    @staticmethod
    def _parse_field(value: str, low: int, high: int, name: str) -> Set[int]:
        allowed: Set[int] = set()

        for part in value.split(','):
            part = part.strip()
            if not part:
                raise ValueError(f"Empty value in cron {name} field")

            step = 1
            if '/' in part:
                part, _, step_text = part.partition('/')
                if not step_text.isdigit() or int(step_text) < 1:
                    raise ValueError(f"Invalid step '{step_text}' in cron {name} field")
                step = int(step_text)

            if part in ('*', ''):
                start, end = low, high
            elif '-' in part.lstrip('-'):
                start_text, _, end_text = part.partition('-')
                start, end = int(start_text), int(end_text)
            else:
                start = end = int(part)

            if not (low <= start <= high and low <= end <= high and start <= end):
                raise ValueError(
                    f"Value '{part}' out of range [{low}-{high}] in cron {name} field"
                )

            allowed.update(range(start, end + 1, step))

        if not allowed:
            raise ValueError(f"Cron {name} field matches nothing: '{value}'")
        return allowed

    def matches(self, moment: datetime) -> bool:
        minute, hour, day, month, weekday = self.fields
        return (
            moment.minute in minute
            and moment.hour in hour
            and moment.day in day
            and moment.month in month
            # cron 中周日为 0，Python 的 weekday() 中周一为 0
            and ((moment.weekday() + 1) % 7) in weekday
        )

    def next_after(self, moment: datetime) -> datetime:
        """返回 moment 之后第一个匹配的时间点（分钟精度）"""
        candidate = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        # 上限为 4 年，覆盖闰年 2/29 这类稀疏表达式
        for _ in range(366 * 4 * 24 * 60):
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        raise ValueError(f"Cron expression '{self.expression}' never matches")


class Scheduler:
    """定时任务调度器"""

    def __init__(self, config: Dict):
        self.config = config
        self.interval_minutes = config.get('interval_minutes', 1440)
        self.run_on_start = config.get('run_on_start', True)
        self.running = False
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.run_count = 0
        self.error_count = 0
        self._stop_event = threading.Event()

        self.cron: Optional[CronExpression] = None
        expression = config.get('cron_expression')
        if config.get('use_cron') and expression:
            try:
                self.cron = CronExpression(expression)
            except ValueError as e:
                logger.error(f"{e}; falling back to interval scheduling")

    @property
    def mode(self) -> str:
        return f"cron({self.cron.expression})" if self.cron else f"every {self.interval_minutes}min"

    def _install_signal_handlers(self):
        """注册停止信号；仅在主线程可用"""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._signal_handler)
            except (ValueError, OSError, AttributeError):
                logger.debug(f"Could not install handler for {sig}")

    def _signal_handler(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down after current task...")
        self.stop()

    def _compute_next_run(self, reference: datetime) -> datetime:
        if self.cron:
            return self.cron.next_after(reference)
        return reference + timedelta(minutes=self.interval_minutes)

    def start(self, task: Callable):
        """启动调度循环，阻塞直到收到停止信号"""
        self._install_signal_handlers()
        self.running = True
        self._stop_event.clear()

        logger.info(f"Scheduler started ({self.mode})")

        if self.run_on_start:
            self._execute(task)
        else:
            self.next_run = self._compute_next_run(datetime.now())
            logger.info(f"Next run scheduled at: {self.next_run:%Y-%m-%d %H:%M:%S}")

        try:
            while self.running:
                now = datetime.now()
                wait_seconds = max((self.next_run - now).total_seconds(), 0) if self.next_run else 60
                # 分片等待，让停止信号最多 30 秒内生效
                if self._stop_event.wait(timeout=min(wait_seconds, 30)):
                    break
                if self.next_run and datetime.now() >= self.next_run:
                    self._execute(task)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.stop()

    def _execute(self, task: Callable):
        """执行一次任务，失败也照常安排下次运行"""
        started = datetime.now()
        logger.info(f"Executing scheduled task at {started:%Y-%m-%d %H:%M:%S}")

        try:
            task()
            self.run_count += 1
        except Exception as e:
            self.error_count += 1
            logger.exception(f"Task execution failed: {e}")

        self.last_run = started
        self.next_run = self._compute_next_run(datetime.now())
        logger.info(f"Next run scheduled at: {self.next_run:%Y-%m-%d %H:%M:%S}")

    def stop(self):
        """停止调度器"""
        if not self.running:
            return
        logger.info("Stopping scheduler...")
        self.running = False
        self._stop_event.set()
        logger.info(
            f"Scheduler stopped (runs: {self.run_count}, errors: {self.error_count})"
        )

    def run_once(self, task: Callable):
        """立即执行一次任务"""
        logger.info("Running task once...")
        task()
        self.run_count += 1
        self.last_run = datetime.now()
        logger.info("Task completed successfully")

    def get_status(self) -> Dict:
        """获取调度器状态"""
        return {
            'running': self.running,
            'mode': self.mode,
            'interval_minutes': self.interval_minutes,
            'cron_expression': self.cron.expression if self.cron else None,
            'run_count': self.run_count,
            'error_count': self.error_count,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
        }
