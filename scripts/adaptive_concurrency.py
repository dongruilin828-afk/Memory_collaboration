"""Batch-local admission control and credential-free request evidence."""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from scripts.cancellation import check_cancelled


class APIUnavailable(RuntimeError):
    pass


class APIDeferred(APIUnavailable):
    """Local scheduling delay; no request failed and no provider is penalized."""
    def __init__(self, message="接口暂忙，任务稍后重新调度。", retry_after=1):
        super().__init__(message)
        self.retry_after = retry_after


class SummaryBudgetExceeded(RuntimeError):
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
    warmup: bool = True
    recovering: bool = False
    epoch: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=12))
    throughput: dict = field(default_factory=dict)


@dataclass
class _ChunkLimit:
    failed_chars: int
    target_chars: int
    epoch: int = 0
    stable: int = 0


class AdaptiveSummaryScheduler:
    def __init__(self, *, on_change=lambda: None, has_pending=lambda: True, clock=time.monotonic, trace_path=None):
        self.condition = threading.Condition()
        self.pools = {}
        self.profiles = {}
        self.on_change, self.has_pending, self.clock = on_change, has_pending, clock
        self.reason = "每个接口从 1 并发开始，根据请求反馈调整"
        self.context = threading.local()
        self.trace_path = Path(trace_path) if trace_path is not None else None
        self.trace_error = False
        self.sequence = self.requests = self.peak_requests = 0
        self.flights = {}
        self.chunk_limits = {}

    def _event(self, event, **values):
        # Called under the scheduler lock; never log URLs, prompts, exceptions or key hashes.
        self.sequence += 1
        if self.trace_path is None:
            return
        row = dict(sequence=self.sequence, time=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                   monotonic=round(self.clock(), 6), event=event,
                   file=values.pop("file", getattr(self.context, "file", None)), **values)
        try:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            self.trace_error = True

    def _pool_id(self, key):
        return list(self.pools).index(key) + 1

    @staticmethod
    def _limit(pool):
        return 1 if pool.recovering else pool.limit

    @contextmanager
    def file(self, index, reservation, budget=None):
        self.context.file, self.context.reservation = index, reservation
        self.context.budget = budget if budget is not None else {"spent": 0, "waited": 0}
        try:
            with self.condition:
                self._event("file_start", profile=reservation[0], pool=self._pool_id(reservation[1]) if reservation[1] else None)
            yield
        finally:
            with self.condition:
                self._event("file_end")
                owner = (threading.get_ident(), index)
                self.flights = {key: value for key, value in self.flights.items() if value != owner}
                self.condition.notify_all()
            del self.context.file, self.context.reservation, self.context.budget

    def claim(self, fingerprints):
        if not hasattr(self.context, "file"):
            return
        key = tuple(sorted(fingerprints))
        owner = (threading.get_ident(), self.context.file)
        with self.condition:
            if self.context.budget["waited"] >= 900:
                raise SummaryBudgetExceeded("文件累计等待接口超过15分钟；已完成进度保留，可稍后重试。")
            if key in self.flights and self.flights[key] != owner:
                self._event("duplicate_wait", leader_file=self.flights[key][1])
                raise APIDeferred("相同输入正在处理，等待完成缓存后复用。")
            self.flights[key] = owner

    def _recent(self, pool):
        while pool.recent and pool.recent[0][0] < self.clock() - 180:
            pool.recent.popleft()
        return [row[1] for row in pool.recent]

    def _score(self, key):
        pool = self.pools[key]
        limit = self._limit(pool)
        recent = self._recent(pool)
        faults = recent.count("transport_error") / max(1, len(recent))
        latency = sum(pool.latency.values()) / max(1, len(pool.latency)) or 30
        wait = max(0, pool.cooldown-self.clock(), pool.next_start-self.clock())
        wait += max(0, pool.active-limit+1) * latency / limit
        return (pool.disabled, wait, pool.recovering, faults, (pool.assigned+pool.active)/limit)

    def rank(self, attempts):
        with self.condition:
            def score(attempt):
                config = attempt[0]
                entries = self.profiles.get(config.api_profile_id or config.provider, ())
                candidates = [self._score(key) for key, model in entries
                              if model == (config.api_protocol, config.model) and self._usable(key, model)]
                return min(candidates) if candidates else (True, float("inf"), True, 1, float("inf"))
            return sorted(attempts, key=score)

    def use(self, config, api_key):
        """Move the file reservation on primary-provider fallback, not on media calls."""
        profile = config.api_profile_id or config.provider
        key, _ = self.register(profile, config, api_key)
        reservation = getattr(self.context, "reservation", None)
        if reservation is None:
            return
        with self.condition:
            previous, old_key, weight = reservation
            if old_key != key:
                if old_key is not None:
                    self.pools[old_key].assigned = max(0, round(self.pools[old_key].assigned - weight, 10))
                weight = weight or 1
                self.pools[key].assigned += weight
            reservation[:] = profile, key, weight
            self._event("provider_attempt", profile=profile.replace(api_key, "[已脱敏]"),
                        model=config.model.replace(api_key, "[已脱敏]"), pool=self._pool_id(key))
            if previous != profile or old_key != key:
                self._event("fallback", previous_profile=previous, profile=profile,
                            previous_pool=self._pool_id(old_key) if old_key else None, pool=self._pool_id(key))
            self.condition.notify_all()
        self.on_change()

    def topic_wait(self, waiting):
        with self.condition:
            self._event("topic_wait_start" if waiting else "topic_wait_end")

    def recover_file(self, index, round_number, delay):
        with self.condition:
            self._event("recovery_queued", file=index, round=round_number, delay_seconds=delay)

    def retry_allowed(self, config, api_key, started, delay):
        key, _ = self.register(config.api_profile_id or config.provider, config, api_key)
        with self.condition:
            allowed = (not self.pools[key].recovering and
                       time.monotonic() - started + delay < config.request_timeout_seconds)
            if not allowed:
                self._event("retry_stopped", pool=self._pool_id(key), reason="重复故障或累计重试预算已用尽")
            return allowed

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

    def _chunk_policy_key(self, config, api_key, platform, chars, message_count):
        key, model = self.register(config.api_profile_id or config.provider, config, api_key)
        density = max(1, chars // max(1, message_count)).bit_length() - 1
        return (key, model, config.thinking_level, config.max_output_tokens, config.json_mode,
                json.dumps(config.reasoning_config, sort_keys=True), platform, density)

    def chunk_target(self, config, api_key, platform, chars, message_count):
        key = self._chunk_policy_key(config, api_key, platform, chars, message_count)
        with self.condition:
            sample = self.chunk_limits.get(key)
            # ponytail: batch-local character/density heuristic; token estimates need real usage samples.
            return sample.target_chars if sample and chars * 5 >= sample.failed_chars * 4 else None

    def chunk_epoch(self, config, api_key, platform, chars, message_count):
        key = self._chunk_policy_key(config, api_key, platform, chars, message_count)
        with self.condition:
            sample = self.chunk_limits.get(key)
            return sample.epoch if sample else None

    def record_chunk_split(self, config, api_key, platform, chars, message_count, target_chars, *, predicted=False):
        key = self._chunk_policy_key(config, api_key, platform, chars, message_count)
        with self.condition:
            if not predicted:
                previous = self.chunk_limits.get(key, _ChunkLimit(chars, target_chars))
                self.chunk_limits[key] = _ChunkLimit(min(previous.failed_chars, chars),
                    max(1000, min(previous.target_chars, target_chars)), previous.epoch + 1)
            self._event("chunk_preempted" if predicted else "chunk_limit_learned",
                        pool=self._pool_id(key[0]), model=config.model.replace(api_key, "[已脱敏]"),
                        chars=chars, message_count=message_count, density_bucket=key[-1], target_chars=target_chars)

    def record_chunk_success(self, config, api_key, platform, chars, message_count, epoch, response):
        key = self._chunk_policy_key(config, api_key, platform, chars, message_count)
        response = response if isinstance(response, dict) else {}
        request_key = self._chunk_policy_key(response.get("request_config", config), api_key, platform, chars, message_count)
        with self.condition:
            sample = self.chunk_limits.get(key)
            if sample is None or epoch != sample.epoch:
                return
            usage = response.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            used = usage.get("completion_tokens")
            if config.provider == "gemini" or config.api_protocol == "google":
                thought = usage.get("reasoning_tokens")
                used = used + thought if type(used) is int and type(thought) is int and thought >= 0 else None
            limit = config.max_output_tokens
            target = min(config.chunk_chars, sample.failed_chars * 4 // 5, sample.target_chars * 5 // 4)
            if (request_key != key or response.get("finish_reason") != "stop" or type(limit) is not int or limit <= 0
                    or response.get("output_limit") != limit or type(used) is not int or used <= 0
                    or used * 5 > limit * 3 or chars * 2 < sample.target_chars
                    or used * target * 4 > limit * chars * 3):
                sample.stable = 0
                return
            sample.stable += 1
            if sample.stable < 3:
                return
            sample.stable = 0
            if target <= sample.target_chars:
                return
            previous = sample.target_chars
            sample.target_chars = target
            sample.epoch += 1
            self._event("chunk_limit_relaxed", pool=self._pool_id(key[0]),
                        model=config.model.replace(api_key, "[已脱敏]"), density_bucket=key[-1],
                        previous_target_chars=previous, target_chars=target,
                        output_tokens=used, output_limit=limit)

    def capacity(self):
        with self.condition:
            return self._capacity_unlocked()

    def can_retry(self):
        with self.condition:
            return any(self._usable(key, model) for entries in self.profiles.values() for key, model in entries)

    def reserve(self, providers, weight=1):
        with self.condition:
            candidates = []
            for order, profile in enumerate(providers):
                for key, model in self.profiles[profile]:
                    pool = self.pools[key]
                    if self._usable(key, model) and pool.cooldown <= self.clock():
                        candidates.append(((self._score(key), order), profile, key))
            if candidates:
                _, profile, key = min(candidates, key=lambda item: item[0])
                self.pools[key].assigned += weight
                return [profile, key, weight]
            return [next(iter(providers)), None, 0]

    def release(self, reservation):
        _, key, weight = reservation
        if key is not None:
            with self.condition:
                self.pools[key].assigned = max(0, round(self.pools[key].assigned - weight, 10))
                self.condition.notify_all()

    def busy_files(self, reservations):
        with self.condition:
            return sum(key is None or (not self.pools[key].disabled and self.pools[key].cooldown <= self.clock())
                       for _, key, _ in reservations)

    def snapshot(self):
        with self.condition:
            cooling = sum(p.cooldown > self.clock() for p in self.pools.values())
            recovering = sum(p.recovering for p in self.pools.values())
            reason = ("部分接口正在冷却，健康接口继续处理" if cooling else
                      "故障接口逐个请求确认恢复" if recovering else
                      "没有可用接口，请检查权限、模型或额度" if not self._capacity_unlocked() else "接口按当前容量运行")
            return dict(capacity=self._capacity_unlocked(), active_requests=sum(p.active for p in self.pools.values()),
                        peak_requests=self.peak_requests, request_count=self.requests,
                        cooling=cooling, recovering=recovering, trace_error=self.trace_error,
                        disabled=sum(p.disabled for p in self.pools.values()), reason=reason, last_adjustment=self.reason,
                        pools=[dict(pool=self._pool_id(key), limit=self._limit(p), active=p.active,
                                    assigned=p.assigned, disabled=p.disabled, recovering=p.recovering,
                                    cooldown_seconds=round(max(0, p.cooldown-self.clock()), 3)) for key, p in self.pools.items()])

    def _capacity_unlocked(self):
        keys = {key for entries in self.profiles.values() for key, model in entries
                if self._usable(key, model) and self.pools[key].cooldown <= self.clock()}
        return min(10, sum(self._limit(self.pools[key]) for key in keys))

    @contextmanager
    def request(self, config, api_key, prompt, cancel_event=None, media_assets=None, request_kind=()):
        key, model = self.register(config.api_profile_id or config.provider, config, api_key)
        queued = self.clock()
        budget = getattr(self.context, "budget", None)
        with self.condition:
            pool = self.pools[key]
            if budget is not None:
                budget.setdefault("limit", config.request_timeout_seconds * 2)
                if budget.get("failed_seconds", 0) >= budget["limit"]:
                    self._event("budget_stopped", reason="本轮失败调用预算已用尽，保留进度等待恢复")
                    raise SummaryBudgetExceeded("本轮失败调用预算已用尽；保留已完成进度，等待自动恢复。")
                if budget["waited"] >= 900:
                    raise SummaryBudgetExceeded("文件累计等待接口超过15分钟；已完成进度保留，可稍后重试。")
            while True:
                check_cancelled(cancel_event)
                if not self._usable(key, model):
                    self._event("admission_stopped", pool=self._pool_id(key), reason="接口或模型在本批已停用")
                    raise APIUnavailable("自动调度：该接口或模型在本批已停用，请检查配置、权限或额度。")
                now = self.clock()
                if now - queued >= 3:
                    if budget is not None:
                        budget["waited"] += now-queued
                    self._event("admission_deferred", pool=self._pool_id(key), wait_seconds=round(now-queued, 6))
                    raise APIDeferred(retry_after=min(5, max(1, pool.cooldown-now)))
                if pool.active < self._limit(pool) and sum(p.active for p in self.pools.values()) < 10 and now >= max(pool.cooldown, pool.next_start):
                    pool.active += 1
                    pool.starts.append(now)
                    while pool.starts and pool.starts[0] < now - 60:
                        pool.starts.popleft()
                    pool.next_start = now + pool.interval
                    epoch = pool.epoch
                    self.requests += 1
                    request_id = self.requests
                    active = sum(p.active for p in self.pools.values())
                    self.peak_requests = max(self.peak_requests, active)
                    self._event("request_start", request=request_id, pool=self._pool_id(key),
                                profile=(config.api_profile_id or config.provider).replace(api_key, "[已脱敏]"),
                                model=config.model.replace(api_key, "[已脱敏]"), thinking=config.thinking_level,
                                stage=list(request_kind), media=bool(media_assets), size_bucket=len(prompt)//4000,
                                wait_seconds=round(now-queued, 6), active_requests=active, limit=self._limit(pool))
                    if budget is not None:
                        budget["waited"] += now-queued
                    break
                self.condition.wait(.1)
        started = self.clock()
        ticket = {"timeout": config.request_timeout_seconds} if budget is not None else {}
        error = None
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
                if budget is not None:
                    budget["spent"] += max(0, now-started)
                status = getattr(error, "status_code", None) or getattr(error, "code", None)
                previous_limit = self._limit(pool)
                throughput_metrics = {}
                outcome = "success" if error is None and ticket.get("valid", True) else "invalid_output"
                if outcome != "success":
                    pool.warmup = False
                    pool.stable = 0
                if error is not None:
                    outcome = "cancelled" if not isinstance(error, Exception) else "content_error"
                if isinstance(error, SummaryBudgetExceeded):
                    outcome = "budget_exhausted"
                if budget is not None and outcome not in {"success", "cancelled", "budget_exhausted"}:
                    budget["failed_seconds"] = budget.get("failed_seconds", 0) + max(0, now-started)
                if status in (401, 402):
                    pool.disabled = True
                    self.reason = "接口鉴权或余额不可用，本批停止分配"
                    outcome = "disabled"
                elif status in (403, 404):
                    pool.blocked.add(model)
                    self.reason = "该模型无权限或不存在，本批停止分配"
                    outcome = "model_blocked"
                elif status == 429:
                    pool.limit = max(1, pool.limit // 2)
                    pool.stable = 0
                    pool.interval = min(60, max(pool.interval * 2, 60 / max(1, len(pool.starts))))
                    pool.cooldown = max(pool.cooldown, now + (ticket.get("retry_after") or retry_seconds(error) or 5))
                    pool.tuned_at = now
                    pool.epoch += 1
                    self.reason = "接口限流，降低容量并按服务端提示冷却"
                    outcome = "rate_limited"
                elif ((ticket.get("transport_error") or isinstance(error, (TimeoutError, OSError))) and status is None) or isinstance(status, int) and status >= 500:
                    pool.faults += 1
                    pool.epoch += 1
                    pool.stable = 0
                    outcome = "transport_error"
                    recent = self._recent(pool)
                    window_faults = recent.count("transport_error") + 1
                    if pool.faults >= 2 or window_faults >= 2 and window_faults / (len(recent)+1) >= .25:
                        pool.faults = max(pool.faults, window_faults)
                        pool.limit = max(1, pool.limit // 2)
                        pool.cooldown = max(pool.cooldown, now + min(60, 2 ** min(6, pool.faults - 1)))
                        pool.recovering = True
                        pool.tuned_at = now
                        self.reason = "连续传输故障，延长冷却后逐个请求确认恢复"
                elif error is None and ticket.get("valid", True) and epoch == pool.epoch:
                    pool.faults = 0
                    # Compare similar request sizes/models, not whole-file wall time.
                    bucket = (model, config.thinking_level, request_kind, bool(media_assets), len(prompt) // 4000)
                    elapsed = max(.001, now - started)
                    baseline = pool.latency.get(bucket, elapsed)
                    pool.latency[bucket] = baseline * .8 + elapsed * .2
                    completions, old_rate = pool.throughput.get(bucket, (deque(maxlen=4), None))
                    completions.append(now)
                    rate = 3 / max(.001, now-completions[0]) if len(completions)==4 else None
                    throughput_ok = old_rate is None or rate is None or rate >= old_rate * .8
                    pool.throughput[bucket] = (completions, old_rate if rate is None else
                        rate if old_rate is None else old_rate*.8+rate*.2)
                    if rate is not None:
                        throughput_metrics["throughput_per_second"] = round(rate, 6)
                    pool.stable = pool.stable + 1 if elapsed <= baseline * 1.5 else 0
                    if pool.recovering:
                        pool.recovering = False
                        pool.stable = 0
                        pool.tuned_at = now
                        self.reason = "恢复请求成功，继续以降低后的容量运行"
                    elif (pool.stable >= (2 if pool.warmup else 4) and now - pool.tuned_at >= 2
                          and "transport_error" not in self._recent(pool) and throughput_ok):
                        if pending:
                            pool.limit = min(10, pool.limit + 1)
                            pool.warmup = False
                        pool.interval = max(.25, pool.interval * .9)
                        pool.stable = 0
                        pool.tuned_at = now
                        self.reason = "请求持续稳定，逐步增加可用容量" if pending else "请求稳定，保持当前容量"
                pool.recent.append((now, outcome))
                self._event("request_end", request=request_id, pool=self._pool_id(key),
                            outcome=outcome, status=status if isinstance(status, int) else None,
                            seconds=round(max(0, now-started), 6), active_requests=sum(p.active for p in self.pools.values()),
                            previous_limit=previous_limit, limit=self._limit(pool),
                            cooldown_seconds=round(max(0, pool.cooldown-now), 3), reason=self.reason,
                            **{name: ticket[name] for name in ("finish_reason", "usage") if name in ticket},
                            **throughput_metrics,
                            error_type=type(error).__name__ if error is not None else None)
                self.condition.notify_all()
            # Never acquire the queue/UI lock while holding the request lock.
            self.on_change()
