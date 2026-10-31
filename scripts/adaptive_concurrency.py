"""Batch-local admission control. No network probes, credentials or history on disk."""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import math
import threading
import time

from scripts.cancellation import check_cancelled


class APIUnavailable(RuntimeError):
    pass


def endpoint_for(config):
    import os
    if config.provider == "custom":
        return config.api_base.rstrip("/")
    return {"gemini": "https://generativelanguage.googleapis.com",
            "deepseek": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
            "siliconflow": os.getenv("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1")}[config.provider].rstrip("/")


def retry_seconds(error):
    headers = getattr(error, "headers", None) or getattr(getattr(error, "response", None), "headers", {})
    value = headers.get("retry-after") or headers.get("Retry-After") if headers else None
    try:
        seconds = float(value)
        return max(0, seconds) if math.isfinite(seconds) else None
    except (ValueError, TypeError):
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


@dataclass
class _Pool:
    limit: int = 1
    active: int = 0
    assigned: float = 0
    disabled: bool = False
    blocked: set = field(default_factory=set)
    cooldown: float = 0
    next_start: float = 0
    interval: float = .25
    stable: int = 0
    faults: int = 0
    tuned_at: float = 0
    starts: deque = field(default_factory=deque)
    latency: dict = field(default_factory=dict)


class AdaptiveSummaryScheduler:
    def __init__(self, *, on_change=lambda: None, has_pending=lambda: True, clock=time.monotonic):
        self.condition = threading.Condition()
        self.pools = {}
        self.profiles = {}
        self.on_change, self.has_pending, self.clock = on_change, has_pending, clock
        self.reason = "每个接口从 1 并发开始，根据请求反馈调整"

    def register(self, profile, config, api_key):
        # Same endpoint/key shares capacity across models and duplicate profiles.
        key = (endpoint_for(config), hashlib.sha256(api_key.encode()).digest())
        model = (config.api_protocol, config.model)
        with self.condition:
            self.pools.setdefault(key, _Pool(tuned_at=self.clock()))
            self.profiles.setdefault(profile, [])
            if (key, model) not in self.profiles[profile]:
                self.profiles[profile].append((key, model))
        return key, model

    def _usable(self, key, model):
        pool = self.pools[key]
        return not pool.disabled and model not in pool.blocked

    def capacity(self):
        with self.condition:
            return self._capacity_unlocked()

    def reserve(self, providers, weight=1):
        with self.condition:
            candidates = []
            for order, profile in enumerate(providers):
                for key, model in self.profiles[profile]:
                    pool = self.pools[key]
                    if self._usable(key, model) and pool.cooldown <= self.clock():
                        candidates.append((((pool.assigned + pool.active) / pool.limit, order), profile, key))
            if candidates:
                _, profile, key = min(candidates, key=lambda item: item[0])
                self.pools[key].assigned += weight
                return profile, key, weight
            return next(iter(providers)), None, 0

    def release(self, reservation):
        _, key, weight = reservation
        if key is not None:
            with self.condition:
                self.pools[key].assigned = max(0, self.pools[key].assigned - weight)
                self.condition.notify_all()

    def busy_files(self, reservations):
        with self.condition:
            return sum(key is None or (not self.pools[key].disabled and self.pools[key].cooldown <= self.clock())
                       for _, key, _ in reservations)

    def snapshot(self):
        with self.condition:
            return dict(capacity=self._capacity_unlocked(), active_requests=sum(p.active for p in self.pools.values()),
                        cooling=sum(p.cooldown > self.clock() for p in self.pools.values()),
                        disabled=sum(p.disabled for p in self.pools.values()), reason=self.reason)

    def _capacity_unlocked(self):
        keys = {key for entries in self.profiles.values() for key, model in entries
                if self._usable(key, model) and self.pools[key].cooldown <= self.clock()}
        return min(10, sum(self.pools[key].limit for key in keys))

    @contextmanager
    def request(self, config, api_key, prompt, cancel_event=None, media_assets=None, request_kind=()):
        key, model = self.register(config.api_profile_id or config.provider, config, api_key)
        with self.condition:
            pool = self.pools[key]
            while True:
                check_cancelled(cancel_event)
                if not self._usable(key, model):
                    raise APIUnavailable("自动调度：该接口或模型在本批已停用，请检查配置、权限或额度。")
                now = self.clock()
                if pool.active < pool.limit and sum(p.active for p in self.pools.values()) < 10 and now >= max(pool.cooldown, pool.next_start):
                    pool.active += 1
                    pool.starts.append(now)
                    while pool.starts and pool.starts[0] < now - 60:
                        pool.starts.popleft()
                    pool.next_start = now + pool.interval
                    break
                self.condition.wait(.1)
        started = self.clock()
        ticket, error = {}, None
        try:
            yield ticket
        except BaseException as caught:
            error = caught
            raise
        finally:
            pending = self.has_pending()
            with self.condition:
                pool.active -= 1
                now = self.clock()
                status = getattr(error, "status_code", None) or getattr(error, "code", None)
                if status in (401, 402):
                    pool.disabled = True
                    self.reason = "接口鉴权或余额不可用，本批停止分配"
                elif status in (403, 404):
                    pool.blocked.add(model)
                    self.reason = "该模型无权限或不存在，本批停止分配"
                elif status == 429:
                    pool.limit = max(1, pool.limit // 2)
                    pool.stable = 0
                    pool.interval = min(60, max(pool.interval * 2, 60 / max(1, len(pool.starts))))
                    pool.cooldown = max(pool.cooldown, now + (ticket.get("retry_after") or retry_seconds(error) or 5))
                    pool.tuned_at = now
                    self.reason = "接口限流，降低容量并按服务端提示冷却"
                elif ((ticket.get("transport_error") or isinstance(error, (TimeoutError, OSError))) and status is None) or isinstance(status, int) and status >= 500:
                    pool.faults += 1
                    pool.stable = 0
                    if pool.faults >= 2:
                        pool.limit = max(1, pool.limit // 2)
                        pool.cooldown = max(pool.cooldown, now + 2)
                        pool.tuned_at = now
                        self.reason = "连续传输故障，暂时降低容量"
                elif error is None and ticket.get("valid", True):
                    pool.faults = 0
                    # Compare similar request sizes/models, not whole-file wall time.
                    bucket = (model, config.thinking_level, request_kind, bool(media_assets), len(prompt) // 4000)
                    elapsed = max(.001, now - started)
                    baseline = pool.latency.get(bucket, elapsed)
                    pool.latency[bucket] = baseline * .8 + elapsed * .2
                    pool.stable = pool.stable + 1 if elapsed <= baseline * 1.5 else 0
                    if pool.stable >= 4 and now - pool.tuned_at >= 2:
                        if pending:
                            pool.limit = min(10, pool.limit + 1)
                        pool.interval = max(.25, pool.interval * .9)
                        pool.stable = 0
                        pool.tuned_at = now
                        self.reason = "请求持续稳定，逐步增加可用容量" if pending else "请求稳定，保持当前容量"
                self.condition.notify_all()
            # Never acquire the queue/UI lock while holding the request lock.
            self.on_change()
