"""轻量级内存登录限流器，用于缓解暴力破解。

无外部依赖、单进程内有效。多进程/多实例部署时应替换为
基于 Redis 的实现（接口保持一致即可）。
"""
import threading
import time
from dataclasses import dataclass, field

# 默认策略：同一 key 在窗口期内失败达到上限后锁定一段时间。
MAX_FAILURES = 5
WINDOW_SECONDS = 5 * 60  # 统计窗口：5 分钟
LOCKOUT_SECONDS = 15 * 60  # 触发后锁定：15 分钟


@dataclass
class _Bucket:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class LoginRateLimiter:
    def __init__(
        self,
        max_failures: int = MAX_FAILURES,
        window_seconds: int = WINDOW_SECONDS,
        lockout_seconds: int = LOCKOUT_SECONDS,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _prune(self, bucket: _Bucket, now: float) -> None:
        cutoff = now - self.window_seconds
        bucket.failures = [t for t in bucket.failures if t >= cutoff]

    def retry_after(self, key: str) -> int:
        """若该 key 当前处于锁定中，返回剩余秒数（>0）；否则返回 0。"""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return 0
            if bucket.locked_until > now:
                return int(bucket.locked_until - now) + 1
            return 0

    def register_failure(self, key: str) -> int:
        """记录一次失败。返回触发锁定后的剩余秒数（未触发则 0）。"""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket())
            self._prune(bucket, now)
            bucket.failures.append(now)
            if len(bucket.failures) >= self.max_failures:
                bucket.locked_until = now + self.lockout_seconds
                bucket.failures.clear()
                return self.lockout_seconds
            return 0

    def reset(self, key: str) -> None:
        """登录成功后清除该 key 的失败计数与锁定。"""
        with self._lock:
            self._buckets.pop(key, None)


login_limiter = LoginRateLimiter()
