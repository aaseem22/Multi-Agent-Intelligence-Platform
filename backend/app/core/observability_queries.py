"""Read-side queries for the observability dashboard: Langfuse traces, observations and scores.

Talks to the Langfuse public REST API with httpx (basic auth public:secret), so keys stay
server-side. It uses the current read APIs only: `GET /api/public/v2/observations` (cursor
pagination, `fields` groups) and `GET /api/public/v3/scores`. The legacy trace, v1 observation,
v2 score and daily-metrics endpoints are gone for new organisations (HTTP 410) and are removed
for everyone on 2026-11-16. A "trace" here is its root observation (`isRootObservation=true`);
its tokens, cost, agents and status are aggregated from the trace's observations. Responses are
cached briefly to spare the free tier: concurrent callers share one in-flight load, calls are capped
in parallel and retried on transient failures, and the last good result is served when Langfuse
blips. Local
`a2a_messages` rows are merged in for peer-call and refusal counts, so A2A numbers work even
when Langfuse lags ingestion. Every public function returns a plain dict and never raises:
without keys, or when Langfuse fails, it returns `{"enabled": False, "reason": ..., "transient": ...}`,
where `transient` says the failure is temporary (network, rate limit, server error) rather than
configuration.

Nothing here names a specific department: agents are read from span names
(`agent:{name}`, `a2a:{sender}->{recipient}`) and from the registry's supervisor.
"""

import asyncio
import json
import logging
import math
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.contracts import A2AMessage
from app.core.registry import registry

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 30.0
HTTP_TIMEOUT_SECONDS = 15.0
MAX_PARALLEL_REQUESTS = 3
MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 0.8
RETRY_MAX_SECONDS = 8.0
OBSERVATIONS_PATH = "/api/public/v2/observations"
SCORES_PATH = "/api/public/v3/scores"
ROOT_PAGE_LIMIT = 100
MAX_ROOT_PAGES = 5
OBSERVATION_PAGE_LIMIT = 1000
MAX_OBSERVATION_PAGES = 10
RUN_PAGE_LIMIT = 200
MAX_RUN_PAGES = 3
SCORE_PAGE_LIMIT = 100
MAX_SCORE_PAGES = 10
ROOT_FIELDS = "core,basic,io,metrics,trace_context"
OBSERVATION_FIELDS = "core,basic,usage,metadata,model"
RUN_FIELDS = "core,basic,io"
SCORE_FIELDS = "details,subject"
LATENCY_TARGET_MS = 45_000
SUPERVISOR_FALLBACK = "ceo"
SUPERVISOR_NODES = ("plan", "synthesise")
AGENT_PREFIX = "agent:"
A2A_PREFIX = "a2a:"
SPAN_METADATA_KEYS = ("agent", "mode", "subtask_id", "hop_count", "chain", "a2a_message_id")

_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
_inflight: dict[tuple[Any, ...], asyncio.Future[Any]] = {}
_request_slots: asyncio.Semaphore | None = None


def _slots() -> asyncio.Semaphore:
    """Created lazily so it binds to the running event loop."""
    global _request_slots
    if _request_slots is None:
        _request_slots = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)
    return _request_slots


class LangfuseUnavailable(Exception):
    """Langfuse is not configured or its API failed; the message is shown to the user."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


def reset_cache() -> None:
    _cache.clear()
    _inflight.clear()


def _disabled(reason: str, *, transient: bool = False) -> dict[str, Any]:
    return {
        "enabled": False,
        "reason": reason,
        "transient": transient,
        "host": get_settings().langfuse_host,
    }


def _unavailable(exc: LangfuseUnavailable) -> dict[str, Any]:
    return _disabled(str(exc), transient=exc.transient)


def _missing_keys_reason() -> str:
    return (
        "Langfuse keys are not set. Add LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
        "(and LANGFUSE_HOST if not using cloud.langfuse.com) to .env, then restart the backend."
    )


# --- HTTP -------------------------------------------------------------------------------------


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    """Exponential backoff, or Langfuse's own Retry-After when it sends one."""
    if response is not None:
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(max(float(header), 0.0), RETRY_MAX_SECONDS)
            except ValueError:
                pass
    return min(RETRY_BASE_SECONDS * 2**attempt, RETRY_MAX_SECONDS)


async def _send(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> httpx.Response:
    """GET with a shared concurrency cap and retries on network errors, 429 and 5xx."""
    query = {k: v for k, v in params.items() if v is not None}
    for attempt in range(MAX_ATTEMPTS):
        last_attempt = attempt == MAX_ATTEMPTS - 1
        try:
            async with _slots():
                response = await client.get(path, params=query)
        except httpx.TransportError as exc:
            if last_attempt:
                raise LangfuseUnavailable(
                    f"Could not reach Langfuse: {type(exc).__name__}", transient=True
                ) from exc
            logger.info("Langfuse %s failed (%s), retrying", path, type(exc).__name__)
            await asyncio.sleep(_retry_delay(attempt, None))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if last_attempt:
                raise LangfuseUnavailable(
                    f"Langfuse is busy (HTTP {response.status_code})", transient=True
                )
            logger.info("Langfuse %s returned %s, retrying", path, response.status_code)
            await asyncio.sleep(_retry_delay(attempt, response))
            continue
        return response
    raise LangfuseUnavailable("Could not reach Langfuse", transient=True)


async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
    response = await _send(client, path, params)
    if response.status_code in (401, 403):
        raise LangfuseUnavailable("Langfuse rejected the API keys (check LANGFUSE_* in .env)")
    if response.status_code == 404:
        raise LookupError(path)
    if response.status_code == 410:
        raise LangfuseUnavailable(f"Langfuse no longer serves {path} (HTTP 410)")
    if response.status_code >= 400:
        raise LangfuseUnavailable(f"Langfuse API returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise LangfuseUnavailable("Langfuse returned a response that is not JSON") from exc


async def _get_cursor_pages(
    client: httpx.AsyncClient, path: str, params: dict[str, Any], limit: int, max_pages: int
) -> list[dict[str, Any]]:
    """Follow `meta.cursor` until it runs out or `max_pages` pages have been read."""
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(max_pages):
        body = await _get(client, path, {**params, "limit": limit, "cursor": cursor})
        if not isinstance(body, dict):
            break
        rows.extend(row for row in body.get("data") or [] if isinstance(row, dict))
        cursor = (body.get("meta") or {}).get("cursor")
        if not cursor:
            break
    return rows


def _name_prefix_filter(prefix: str) -> str:
    return json.dumps(
        [{"type": "string", "column": "name", "operator": "starts with", "value": prefix}]
    )


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        base_url=settings.langfuse_host.rstrip("/"),
        auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"Accept": "application/json"},
    )


async def _cached(key: tuple[Any, ...], loader: Any) -> Any:
    """Fresh value from cache, else one shared load. If that load fails for a transient reason,
    the last good value is served instead, so a network blip never blanks the dashboard."""
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]
    pending = _inflight.get(key)
    if pending is None:
        pending = asyncio.ensure_future(loader())
        _inflight[key] = pending
        pending.add_done_callback(lambda _: _inflight.pop(key, None))
    try:
        value = await asyncio.shield(pending)
    except LangfuseUnavailable as exc:
        if exc.transient and hit is not None:
            logger.warning("Langfuse unavailable (%s); serving the last good result", exc)
            return hit[1]
        raise
    _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, value)
    return value


# --- Parsing helpers ----------------------------------------------------------------------------


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _duration_ms(obs: dict[str, Any]) -> float | None:
    start, end = _parse_time(obs.get("startTime")), _parse_time(obs.get("endTime"))
    if start is None or end is None:
        return None
    return max((end - start).total_seconds() * 1000, 0.0)


def _json_value(value: Any) -> Any:
    """v2 returns input/output as raw strings; decode JSON when it is JSON."""
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _tokens(obs: dict[str, Any]) -> int:
    total = obs.get("totalUsage")
    if isinstance(total, int | float) and total:
        return int(total)
    details = obs.get("usageDetails") or {}
    if isinstance(details, dict) and details:
        if "total" in details:
            return int(details["total"] or 0)
        return int(sum(v for k, v in details.items() if isinstance(v, int | float)))
    usage = obs.get("usage") or {}
    if isinstance(usage, dict):
        total = usage.get("total") or (usage.get("input") or 0) + (usage.get("output") or 0)
        return int(total or 0)
    return 0


def _type(obs: dict[str, Any]) -> str:
    return str(obs.get("type") or "").upper()


def _name(obs: dict[str, Any]) -> str:
    return str(obs.get("name") or "")


def _a2a_pair(name: str) -> tuple[str, str] | None:
    if not name.startswith(A2A_PREFIX) or "->" not in name:
        return None
    sender, _, recipient = name.removeprefix(A2A_PREFIX).partition("->")
    return (sender, recipient) if sender and recipient else None


def _run_agent(obs: dict[str, Any]) -> str | None:
    """The agent an `agent:*` or `a2a:*` span runs, or None for other observations."""
    name = _name(obs)
    if name.startswith(AGENT_PREFIX):
        return name.removeprefix(AGENT_PREFIX) or None
    pair = _a2a_pair(name)
    return pair[1] if pair else None


def _obs_kind(obs: dict[str, Any]) -> str:
    name, kind = _name(obs), _type(obs)
    if name.startswith(A2A_PREFIX):
        return "a2a"
    if name.startswith(AGENT_PREFIX):
        return "agent"
    if kind == "GENERATION":
        return "llm"
    if kind == "TOOL":
        return "tool"
    if kind == "EVENT":
        return "event"
    return "span"


def _run_failed(obs: dict[str, Any]) -> bool:
    if str(obs.get("level") or "").upper() == "ERROR":
        return True
    output = _json_value(obs.get("output"))
    if isinstance(output, dict):
        result = output.get("result")
        if isinstance(result, dict) and result.get("status") == "failed":
            return True
    return False


def _question(trace: dict[str, Any]) -> str:
    value = _json_value(trace.get("input"))
    if isinstance(value, dict):
        value = value.get("question") or value.get("message") or value.get("input")
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return text[:500]


def _span_metadata(obs: dict[str, Any]) -> dict[str, Any]:
    metadata = obs.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    return {k: metadata[k] for k in SPAN_METADATA_KEYS if k in metadata}


def _trace_url(trace: dict[str, Any]) -> str:
    host = get_settings().langfuse_host.rstrip("/")
    project = trace.get("projectId")
    if isinstance(project, str) and project:
        return f"{host}/project/{project}/traces/{trace.get('id', '')}"
    return f"{host}/trace/{trace.get('id', '')}"


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(pct / 100 * len(ordered)) - 1, 0)
    return ordered[index]


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _supervisor_name() -> str:
    supervisor = registry.supervisor
    return supervisor.card.name if supervisor else SUPERVISOR_FALLBACK


def _score_passed(score: dict[str, Any]) -> bool:
    value = score.get("value")
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value >= 0.5
    return str(score.get("stringValue") or value).lower() in ("true", "1", "pass", "passed")


# --- Window snapshot ----------------------------------------------------------------------------


@dataclass
class Window:
    days: int
    start: datetime
    end: datetime
    traces: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    scores: list[dict[str, Any]]
    a2a: list[A2AMessage] = field(default_factory=list)

    def obs_by_trace(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for obs in self.observations:
            grouped[str(obs.get("traceId"))].append(obs)
        return grouped

    def scores_by_trace(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for score in self.scores:
            grouped[str(score.get("traceId"))].append(score)
        return grouped


async def _local_a2a(since: datetime) -> list[A2AMessage]:
    """Local A2A log rows since `since`. Failures are logged and give an empty list."""
    try:
        from app.data.repositories import platform

        messages = await platform.list_a2a_messages()
    except Exception as exc:
        logger.warning("Could not read the local A2A log: %s", exc)
        return []
    result = []
    for message in messages:
        created = message.created_at
        created = created if created.tzinfo else created.replace(tzinfo=UTC)
        if created >= since:
            result.append(message)
    return result


def _normalise_score(score: dict[str, Any]) -> dict[str, Any]:
    """A v3 score as a flat dict with `traceId` (v3 nests it under `subject`)."""
    subject = score.get("subject") if isinstance(score.get("subject"), dict) else {}
    trace_id = score.get("traceId")
    if trace_id is None and subject.get("kind") == "trace":
        trace_id = subject.get("id")
    return {**score, "traceId": trace_id}


def _trace_from_root(root: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    """A trace-shaped dict built from its root observation plus its observations' usage."""
    latency = root.get("latency")
    if not isinstance(latency, int | float):
        duration = _duration_ms(root)
        latency = duration / 1000 if duration is not None else None
    costs = [float(c) for o in observations if isinstance(c := o.get("totalCost"), int | float)]
    return {
        "id": str(root.get("traceId")),
        "name": root.get("traceName") or root.get("name"),
        "timestamp": root.get("startTime"),
        "input": root.get("input"),
        "sessionId": root.get("sessionId") or None,
        "tags": [t for t in root.get("tags") or [] if isinstance(t, str)],
        "latency": latency,
        "totalCost": round(sum(costs), 6) if costs else None,
        "projectId": root.get("projectId"),
    }


def _merge_run_outputs(
    observations: list[dict[str, Any]], runs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach agent/a2a run outputs (fetched separately, `io` is heavy) to their observations."""
    outputs = {str(r.get("id")): r.get("output") for r in runs}
    if not outputs:
        return observations
    return [
        {**o, "output": outputs[str(o.get("id"))]} if str(o.get("id")) in outputs else o
        for o in observations
    ]


def _unique_roots(roots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique = []
    for root in roots:
        trace_id = str(root.get("traceId"))
        if trace_id not in seen:
            seen.add(trace_id)
            unique.append(root)
    return unique


async def _fetch_runs(client: httpx.AsyncClient, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Agent and peer-call spans with their outputs, so failed runs can be recognised."""
    batches = await asyncio.gather(
        *(
            _get_cursor_pages(
                client,
                OBSERVATIONS_PATH,
                {**params, "fields": RUN_FIELDS, "filter": _name_prefix_filter(prefix)},
                RUN_PAGE_LIMIT,
                MAX_RUN_PAGES,
            )
            for prefix in (AGENT_PREFIX, A2A_PREFIX)
        )
    )
    return [row for batch in batches for row in batch]


async def _load_window(days: int) -> Window:
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    since = start.isoformat().replace("+00:00", "Z")
    window_params = {"fromStartTime": since}
    async with _client() as client:
        roots, observations, runs, scores = await asyncio.gather(
            _get_cursor_pages(
                client,
                OBSERVATIONS_PATH,
                {**window_params, "isRootObservation": "true", "fields": ROOT_FIELDS},
                ROOT_PAGE_LIMIT,
                MAX_ROOT_PAGES,
            ),
            _get_cursor_pages(
                client,
                OBSERVATIONS_PATH,
                {**window_params, "fields": OBSERVATION_FIELDS},
                OBSERVATION_PAGE_LIMIT,
                MAX_OBSERVATION_PAGES,
            ),
            _fetch_runs(client, window_params),
            _get_cursor_pages(
                client,
                SCORES_PATH,
                {"fromTimestamp": since, "fields": SCORE_FIELDS},
                SCORE_PAGE_LIMIT,
                MAX_SCORE_PAGES,
            ),
        )
    observations = _merge_run_outputs(observations, runs)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        grouped[str(obs.get("traceId"))].append(obs)
    traces = [_trace_from_root(r, grouped[str(r.get("traceId"))]) for r in _unique_roots(roots)]
    traces.sort(key=lambda t: str(t.get("timestamp") or ""), reverse=True)
    return Window(days, start, end, traces, observations, [_normalise_score(s) for s in scores])


async def _window(days: int) -> Window:
    window: Window = await _cached(("window", days), lambda: _load_window(days))
    window.a2a = await _local_a2a(window.start)
    return window


def _guarded_settings_check() -> str | None:
    return None if get_settings().langfuse_enabled else _missing_keys_reason()


# --- Summary --------------------------------------------------------------------------------------


def _trace_latency_ms(trace: dict[str, Any]) -> float | None:
    latency = trace.get("latency")
    return float(latency) * 1000 if isinstance(latency, int | float) else None


def _is_error(obs: dict[str, Any]) -> bool:
    return str(obs.get("level") or "").upper() == "ERROR"


def _roots(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {str(o.get("id")) for o in observations}
    return [
        o
        for o in observations
        if o.get("isRootObservation") is True or o.get("parentObservationId") not in ids
    ]


def _trace_status(observations: list[dict[str, Any]], scores: list[dict[str, Any]]) -> str:
    """error: the request itself failed (root span errored). partial: an agent run or an eval
    check failed. Errors on inner spans alone (e.g. an LLM call that was retried) do not count."""
    if any(_is_error(o) for o in _roots(observations)):
        return "error"
    runs = [o for o in observations if _run_agent(o)]
    if any(_run_failed(o) for o in runs) or any(not _score_passed(s) for s in scores):
        return "partial"
    return "ok"


def _trace_agents(trace: dict[str, Any], observations: list[dict[str, Any]]) -> list[str]:
    names = {agent for o in observations if (agent := _run_agent(o))}
    names.update(t for t in trace.get("tags") or [] if isinstance(t, str) and ":" not in t)
    return sorted(names)


def _nearest_run(obs: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str | None:
    """Walk up the parent chain to the closest agent run and return its agent name."""
    seen: set[str] = set()
    parent_id = obs.get("parentObservationId")
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id.get(parent_id)
        if parent is None:
            return None
        agent = _run_agent(parent)
        if agent:
            return agent
        parent_id = parent.get("parentObservationId")
    return None


def _tool_owner(obs: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str | None:
    """The agent that called a tool: run metadata inherited by the tool span, else its ancestry."""
    metadata = obs.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("agent"), str):
        return metadata["agent"]
    return _nearest_run(obs, by_id)


def _per_agent(window: Window, trace_status: dict[str, str]) -> list[dict[str, Any]]:
    by_id = {str(o.get("id")): o for o in window.observations}
    runs: dict[str, list[float]] = defaultdict(list)
    counts: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    for obs in window.observations:
        agent = _run_agent(obs)
        if agent:
            counts[agent] += 1
            if (duration := _duration_ms(obs)) is not None:
                runs[agent].append(duration)
            failures[agent] += int(_run_failed(obs))
        elif _type(obs) == "TOOL" and (owner := _tool_owner(obs, by_id)):
            tools[owner] += 1
    rows = [
        {
            "agent": agent,
            "runs": counts[agent],
            "avg_latency_ms": _round(_mean(runs[agent])),
            "tool_calls": tools[agent],
            "failures": failures[agent],
            "role": "department",
        }
        for agent in sorted(counts)
    ]
    return [_supervisor_row(window, trace_status), *rows] if window.traces else rows


def _supervisor_row(window: Window, trace_status: dict[str, str]) -> dict[str, Any]:
    per_trace: dict[str, float] = defaultdict(float)
    for obs in window.observations:
        if _name(obs) in SUPERVISOR_NODES and (duration := _duration_ms(obs)) is not None:
            per_trace[str(obs.get("traceId"))] += duration
    return {
        "agent": _supervisor_name(),
        "runs": len(window.traces),
        "avg_latency_ms": _round(_mean(per_trace.values())),
        "tool_calls": 0,
        "failures": sum(1 for s in trace_status.values() if s == "error"),
        "role": "supervisor",
    }


def _edges(window: Window) -> list[dict[str, Any]]:
    """A2A traffic as edges. Local log first (authoritative); Langfuse spans as fallback."""
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def bump(source: str, target: str, kind: str, at: datetime | None, refused: bool) -> None:
        edge = edges.setdefault(
            (source, target, kind),
            {"source": source, "target": target, "kind": kind, "count": 0, "refusals": 0},
        )
        edge["count"] += int(not refused)
        edge["refusals"] += int(refused)
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=UTC)  # the local A2A log stores naive UTC timestamps
        stamp = at.isoformat() if at else None
        if stamp and (edge.get("last_at") is None or stamp > edge["last_at"]):
            edge["last_at"] = stamp

    supervisor = _supervisor_name()
    peer_requests = [m for m in window.a2a if m.type == "peer_request"]
    for message in peer_requests:
        refused = bool(message.payload.get("refused"))
        bump(message.sender, message.recipient, "peer", message.created_at, refused)
    for obs in window.observations:
        start = _parse_time(obs.get("startTime"))
        if _name(obs).startswith(AGENT_PREFIX) and (agent := _run_agent(obs)):
            bump(supervisor, agent, "task", start, False)
        elif not peer_requests and (pair := _a2a_pair(_name(obs))):
            bump(pair[0], pair[1], "peer", start, False)
    for edge in edges.values():
        edge.setdefault("last_at", None)
    return sorted(edges.values(), key=lambda e: (e["kind"], e["source"], e["target"]))


def _bucket_edges(window: Window) -> tuple[list[datetime], timedelta]:
    hourly = window.days <= 2
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    if hourly:
        first = window.start.replace(minute=0, second=0, microsecond=0)
    else:
        first = window.start.replace(hour=0, minute=0, second=0, microsecond=0)
    buckets = []
    cursor = first
    while cursor <= window.end:
        buckets.append(cursor)
        cursor += step
    return buckets, step


def _timeseries(window: Window, tokens_by_trace: dict[str, int]) -> list[dict[str, Any]]:
    buckets, step = _bucket_edges(window)
    if not buckets:
        return []
    latencies: dict[int, list[float]] = defaultdict(list)
    counts: Counter[int] = Counter()
    tokens: Counter[int] = Counter()
    for trace in window.traces:
        stamp = _parse_time(trace.get("timestamp"))
        if stamp is None:
            continue
        index = min(max(int((stamp - buckets[0]) / step), 0), len(buckets) - 1)
        counts[index] += 1
        tokens[index] += tokens_by_trace.get(str(trace.get("id")), 0)
        if (latency := _trace_latency_ms(trace)) is not None:
            latencies[index].append(latency)
    return [
        {
            "bucket": bucket.isoformat(),
            "traces": counts[i],
            "avg_latency_ms": _round(_mean(latencies[i])),
            "tokens": tokens[i],
        }
        for i, bucket in enumerate(buckets)
    ]


def _score_summary(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for score in scores:
        grouped[str(score.get("name") or "score")].append(_score_passed(score))
    return [
        {"name": name, "pass_rate": round(sum(v) / len(v), 4), "count": len(v)}
        for name, v in sorted(grouped.items())
    ]


def _peer_counts(window: Window) -> tuple[int, int]:
    requests = [m for m in window.a2a if m.type == "peer_request"]
    if requests:
        refusals = sum(1 for m in requests if m.payload.get("refused"))
        return len(requests) - refusals, refusals
    return sum(1 for o in window.observations if _a2a_pair(_name(o))), 0


def build_summary(window: Window) -> dict[str, Any]:
    obs_by_trace, scores_by_trace = window.obs_by_trace(), window.scores_by_trace()
    trace_ids = [str(t.get("id")) for t in window.traces]
    status = {tid: _trace_status(obs_by_trace[tid], scores_by_trace[tid]) for tid in trace_ids}
    tokens_by_trace = {tid: sum(_tokens(o) for o in obs_by_trace[tid]) for tid in trace_ids}
    latencies = [v for t in window.traces if (v := _trace_latency_ms(t)) is not None]
    peer_calls, refusals = _peer_counts(window)
    kinds = Counter(_type(o) for o in window.observations)
    errors = sum(1 for s in status.values() if s == "error")
    return {
        "enabled": True,
        "reason": None,
        "host": get_settings().langfuse_host,
        "window": {
            "days": window.days,
            "start": window.start.isoformat(),
            "end": window.end.isoformat(),
            "bucket": "hour" if window.days <= 2 else "day",
        },
        "supervisor": _supervisor_name(),
        "latency_target_ms": LATENCY_TARGET_MS,
        "traces": len(window.traces),
        "avg_latency_ms": _round(_mean(latencies)),
        "p95_latency_ms": _round(_percentile(latencies, 95)),
        "total_tokens": sum(_tokens(o) for o in window.observations),
        "total_cost": round(sum(float(t.get("totalCost") or 0) for t in window.traces), 6),
        "llm_calls": kinds["GENERATION"],
        "tool_calls": kinds["TOOL"],
        "peer_calls": peer_calls,
        "refusals": refusals,
        "error_rate": round(errors / len(trace_ids), 4) if trace_ids else 0.0,
        "success_rate": (
            round(sum(1 for s in status.values() if s == "ok") / len(trace_ids), 4)
            if trace_ids
            else None
        ),
        "per_agent": _per_agent(window, status),
        "scores": _score_summary(window.scores),
        "edges": _edges(window),
        "timeseries": _timeseries(window, tokens_by_trace),
    }


# --- Trace list -------------------------------------------------------------------------------


def _score_marks(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for score in scores:
        grouped[str(score.get("name") or "score")].append(_score_passed(score))
    return [
        {"name": name, "passed": sum(v), "total": len(v)} for name, v in sorted(grouped.items())
    ]


def _local_by_trace(messages: list[A2AMessage]) -> dict[str, tuple[int, int]]:
    grouped: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for message in messages:
        if message.type != "peer_request" or not message.trace_id:
            continue
        grouped[message.trace_id][1 if message.payload.get("refused") else 0] += 1
    return {k: (v[0], v[1]) for k, v in grouped.items()}


def build_trace_list(window: Window, limit: int) -> dict[str, Any]:
    obs_by_trace, scores_by_trace = window.obs_by_trace(), window.scores_by_trace()
    local = _local_by_trace(window.a2a)
    items = []
    for trace in window.traces[:limit]:
        tid = str(trace.get("id"))
        observations = obs_by_trace[tid]
        spans_peer = sum(1 for o in observations if _a2a_pair(_name(o)))
        peer, refused = local.get(tid, (spans_peer, 0))
        items.append(
            {
                "id": tid,
                "name": trace.get("name"),
                "question": _question(trace),
                "timestamp": trace.get("timestamp"),
                "latency_ms": _round(_trace_latency_ms(trace)),
                "tokens": sum(_tokens(o) for o in observations),
                "cost": trace.get("totalCost"),
                "agents": _trace_agents(trace, observations),
                "tags": [t for t in trace.get("tags") or [] if isinstance(t, str)],
                "session_id": trace.get("sessionId"),
                "status": _trace_status(observations, scores_by_trace[tid]),
                "peer_calls": peer,
                "refusals": refused,
                "scores": _score_marks(scores_by_trace[tid]),
                "url": _trace_url(trace),
            }
        )
    return {"enabled": True, "reason": None, "host": get_settings().langfuse_host, "traces": items}


# --- Trace detail -------------------------------------------------------------------------------


def _depths(observations: list[dict[str, Any]]) -> dict[str, int]:
    by_id = {str(o.get("id")): o for o in observations}
    depths: dict[str, int] = {}

    def depth(obs_id: str, guard: int = 0) -> int:
        if obs_id in depths:
            return depths[obs_id]
        parent = by_id.get(obs_id, {}).get("parentObservationId")
        value = (
            0 if not parent or parent not in by_id or guard > 64 else depth(parent, guard + 1) + 1
        )
        depths[obs_id] = value
        return value

    for obs_id in by_id:
        depth(obs_id)
    return depths


def _hop_from_local(pair: tuple[str, str], messages: list[A2AMessage]) -> dict[str, Any]:
    for message in messages:
        if message.type == "peer_request" and (message.sender, message.recipient) == pair:
            return {"hop_count": message.hop_count, "chain": message.chain}
    return {}


def _observation_row(obs: dict[str, Any], depth: int, messages: list[A2AMessage]) -> dict[str, Any]:
    metadata = _span_metadata(obs)
    pair = _a2a_pair(_name(obs))
    if pair and "hop_count" not in metadata:
        metadata.update(_hop_from_local(pair, messages))
    return {
        "id": str(obs.get("id")),
        "parent_id": obs.get("parentObservationId"),
        "name": _name(obs),
        "type": _type(obs),
        "kind": _obs_kind(obs),
        "depth": depth,
        "start": obs.get("startTime"),
        "end": obs.get("endTime"),
        "latency_ms": _round(_duration_ms(obs)),
        "model": obs.get("model"),
        "tokens": _tokens(obs),
        "level": obs.get("level"),
        "status_message": obs.get("statusMessage"),
        "failed": _run_failed(obs) if _run_agent(obs) else False,
        "metadata": metadata,
    }


def _a2a_row(message: A2AMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "sender": message.sender,
        "recipient": message.recipient,
        "type": message.type,
        "hop_count": message.hop_count,
        "chain": message.chain,
        "refused": bool(message.payload.get("refused")),
        "reason": message.payload.get("reason"),
        "content": message.content[:300],
        "created_at": (
            message.created_at
            if message.created_at.tzinfo
            else message.created_at.replace(tzinfo=UTC)
        ).isoformat(),
    }


def _ordered_tree(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Depth-first order (parents before children, siblings by start time)."""
    ids = {str(o.get("id")) for o in observations}
    children: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        parent = obs.get("parentObservationId")
        children[parent if parent in ids else None].append(obs)
    ordered: list[dict[str, Any]] = []
    stack = sorted(children[None], key=lambda o: str(o.get("startTime")), reverse=True)
    while stack:
        obs = stack.pop()
        ordered.append(obs)
        kids = sorted(children[str(obs.get("id"))], key=lambda o: str(o.get("startTime")))
        stack.extend(reversed(kids))
    return ordered


def build_trace_detail(
    trace: dict[str, Any],
    observations: list[dict[str, Any]],
    scores: list[dict[str, Any]],
    messages: list[A2AMessage],
) -> dict[str, Any]:
    depths = _depths(observations)
    rows = [
        _observation_row(o, depths.get(str(o.get("id")), 0), messages)
        for o in _ordered_tree(observations)
    ]
    return {
        "enabled": True,
        "reason": None,
        "host": get_settings().langfuse_host,
        "trace": {
            "id": str(trace.get("id")),
            "name": trace.get("name"),
            "question": _question(trace),
            "timestamp": trace.get("timestamp"),
            "latency_ms": _round(_trace_latency_ms(trace)),
            "tokens": sum(_tokens(o) for o in observations),
            "cost": trace.get("totalCost"),
            "agents": _trace_agents(trace, observations),
            "tags": [t for t in trace.get("tags") or [] if isinstance(t, str)],
            "session_id": trace.get("sessionId"),
            "status": _trace_status(observations, scores),
            "url": _trace_url(trace),
        },
        "observations": rows,
        "scores": [
            {
                "name": s.get("name"),
                "value": s.get("value"),
                "passed": _score_passed(s),
                "comment": s.get("comment"),
                "agent": (s.get("metadata") or {}).get("agent")
                if isinstance(s.get("metadata"), dict)
                else None,
                "timestamp": s.get("timestamp"),
            }
            for s in scores
        ],
        "a2a": [_a2a_row(m) for m in messages],
    }


async def _trace_messages(trace_id: str) -> list[A2AMessage]:
    try:
        from app.data.repositories import platform

        messages = await platform.list_a2a_messages()
    except Exception as exc:
        logger.warning("Could not read the local A2A log: %s", exc)
        return []
    return [m for m in messages if m.trace_id == trace_id]


# --- Public entry points --------------------------------------------------------------------------


async def observability_summary(days: int = 7) -> dict[str, Any]:
    if reason := _guarded_settings_check():
        return _disabled(reason)
    try:
        return build_summary(await _window(days))
    except LangfuseUnavailable as exc:
        return _unavailable(exc)
    except LookupError:
        return _disabled("Not found")
    except Exception as exc:
        logger.exception("Observability summary failed")
        return _disabled(f"Could not build the summary: {type(exc).__name__}")


async def observability_traces(limit: int = 50, days: int = 7) -> dict[str, Any]:
    if reason := _guarded_settings_check():
        return {**_disabled(reason), "traces": []}
    try:
        return build_trace_list(await _window(days), limit)
    except LangfuseUnavailable as exc:
        return {**_unavailable(exc), "traces": []}
    except Exception as exc:
        logger.exception("Observability trace list failed")
        return {**_disabled(f"Could not list traces: {type(exc).__name__}"), "traces": []}


@dataclass
class TraceBundle:
    trace: dict[str, Any]
    observations: list[dict[str, Any]]
    scores: list[dict[str, Any]]


async def _load_trace(trace_id: str) -> TraceBundle:
    params = {"traceId": trace_id}
    async with _client() as client:
        observations, roots, runs, scores = await asyncio.gather(
            _get_cursor_pages(
                client,
                OBSERVATIONS_PATH,
                {**params, "fields": OBSERVATION_FIELDS},
                OBSERVATION_PAGE_LIMIT,
                MAX_OBSERVATION_PAGES,
            ),
            _get_cursor_pages(
                client,
                OBSERVATIONS_PATH,
                {**params, "isRootObservation": "true", "fields": ROOT_FIELDS},
                ROOT_PAGE_LIMIT,
                1,
            ),
            _fetch_runs(client, params),
            _get_cursor_pages(
                client,
                SCORES_PATH,
                {**params, "fields": SCORE_FIELDS},
                SCORE_PAGE_LIMIT,
                MAX_SCORE_PAGES,
            ),
        )
    if not observations and not roots:
        raise LookupError(trace_id)
    observations = _merge_run_outputs(observations, runs)
    root = roots[0] if roots else min(observations, key=lambda o: str(o.get("startTime")))
    return TraceBundle(
        trace=_trace_from_root({**root, "traceId": trace_id}, observations),
        observations=observations,
        scores=[_normalise_score(s) for s in scores],
    )


async def observability_trace(trace_id: str) -> dict[str, Any] | None:
    """Detail for one trace, a disabled payload, or None when Langfuse has no such trace."""
    if reason := _guarded_settings_check():
        return _disabled(reason)
    try:
        bundle: TraceBundle = await _cached(("trace", trace_id), lambda: _load_trace(trace_id))
    except LookupError:
        return None
    except LangfuseUnavailable as exc:
        return _unavailable(exc)
    except Exception as exc:
        logger.exception("Observability trace detail failed")
        return _disabled(f"Could not load the trace: {type(exc).__name__}")
    try:
        messages = await _trace_messages(trace_id)
        return build_trace_detail(bundle.trace, bundle.observations, bundle.scores, messages)
    except Exception as exc:
        logger.exception("Observability trace detail could not be built")
        return _disabled(f"Could not read the trace: {type(exc).__name__}")
