import asyncio
import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from disclosure_ai.services.business import RunCancelled


def canonical_url(url):
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True))),
            "",
        )
    )


def normalize(args):
    if not isinstance(args, dict):
        raise ValueError("INVALID_TOOL_INPUT")
    result = dict(args)
    for key in ("query", "as_of"):
        if key in result:
            if not isinstance(result[key], str):
                raise ValueError("INVALID_TOOL_INPUT")
            result[key] = " ".join(unicodedata.normalize("NFC", result[key]).split())
    if "as_of" in result and re.fullmatch(r"\d{8}", result["as_of"]):
        value = result["as_of"]
        result["as_of"] = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    json.dumps(result, allow_nan=False)
    return result


def cache_key(scope, name, args):
    return hashlib.sha256(
        json.dumps([scope, name, args], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def call(harness, name, args, invoke, *, report=False, scope=""):
    if harness.guard and name != "business_save_report":
        await harness.guard(harness.task_id)
    try:
        args = normalize(args)
    except (ValueError, TypeError):
        return {"error": "INVALID_TOOL_INPUT"}
    key = cache_key(scope, name, args)
    cached = harness.ledger.cached(harness.task_id, key)
    if cached is not None:
        return cached
    if key in harness.inflight:
        try:
            return await asyncio.wait_for(
                asyncio.shield(harness.inflight[key]), max(0.01, min(10, harness.remaining(report)))
            )
        except TimeoutError:
            return {"error": "WAIT_LIMIT"}
    previous = harness.ledger.db.execute(
        "SELECT state FROM lookup_jobs WHERE run_id=? AND cache_key=?", (harness.task_id, key)
    ).fetchone()
    if previous and previous[0] in {"RUNNING", "INTERRUPTED"}:
        harness.ledger.lookup_state(harness.task_id, key, name, "INTERRUPTED")
        harness.ledger.event(harness.task_id, "LOOKUP_RECOVERED", tool=name)
    future = asyncio.get_running_loop().create_future()
    harness.inflight[key] = future
    result = {"error": "TOOL_FAILED"}
    try:
        for attempt in range(3):
            async with harness.ledger.lock:
                row = harness.ledger.row(harness.task_id)
                counts = json.loads(row["tools"])
                if (
                    counts.get(name, 0) >= 3
                    or harness.remaining(report) <= 0
                    or (not report and row["tokens"] >= 64000)
                ):
                    result = {"error": "LIMIT_REACHED"}
                    break
                counts[name] = counts.get(name, 0) + 1
                harness.ledger.db.execute(
                    "UPDATE runs SET tools=? WHERE id=?", (json.dumps(counts), harness.task_id)
                )
                harness.ledger.lookup_state(harness.task_id, key, name, "RUNNING", counts[name])
            try:
                async with asyncio.timeout(min(10, harness.remaining(report))):
                    result = await invoke(name, args)
                if not isinstance(result, dict):
                    result = {"error": "INVALID_TOOL_OUTPUT"}
                if result.get("error") and result.get("retryable") and attempt < 2:
                    continue
                break
            except RunCancelled:
                raise
            except (httpx.TransportError, httpx.HTTPStatusError, TimeoutError) as error:
                result = {"error": type(error).__name__}
                retryable = not isinstance(
                    error, httpx.HTTPStatusError
                ) or error.response.status_code in {429, 500, 502, 503, 504}
                if not retryable or attempt == 2:
                    break
            except Exception as error:
                result = {"error": type(error).__name__}
                break
        harness.ledger.cache(harness.task_id, key, result, scope)
        harness.ledger.lookup_state(
            harness.task_id, key, name, "FAILED" if result.get("error") else "COMPLETED"
        )
        harness.ledger.event(harness.task_id, "TOOL_END", tool=name, error=result.get("error"))
        return result
    except BaseException:
        result = {"error": "INTERRUPTED"}
        harness.ledger.lookup_state(harness.task_id, key, name, "INTERRUPTED")
        raise
    finally:
        if not future.done():
            future.set_result(result)
        harness.inflight.pop(key, None)
