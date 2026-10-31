"""Dedicated persistent browser session: read public API JSON, never daily Chrome data."""

import asyncio
import fcntl
import json
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from app.connectors.douyin_series import comments, first_episode
from app.connectors.redfox import AdapterError

ROOT = Path(__file__).resolve().parents[3] / "data/douyin"
SESSION = ROOT / "browser-session"
BINARIES = ROOT / "browser-binaries"
EPISODES = "/aweme/v1/web/series/aweme/"
COMMENTS = "/aweme/v1/web/comment/list/"


def sample_bundle(responses, series_id, uid):
    episode = next(
        (
            r
            for r in responses
            if r["path"] == EPISODES
            and r["status"] == 200
            and r["parameters"].get("series_id") == series_id
        ),
        None,
    )
    if episode is None:
        return {
            "aweme_id": None,
            "comments": [],
            "episode_response": None,
            "comment_responses": [],
            "sample_complete": False,
        }
    aid = first_episode(episode["body"], series_id, uid)
    rows, selected, seen, finished, pages = [], [], set(), False, {}
    for r in responses:
        if r["path"] != COMMENTS or r["status"] != 200 or r["parameters"].get("aweme_id") != aid:
            continue
        cursor = r["parameters"].get("cursor")
        if cursor is None or not cursor.isdecimal() or int(cursor) >= 15:
            continue
        pages.setdefault(int(cursor), r)
    cursor, visited, source_slots = 0, set(), 0
    while cursor in pages and cursor not in visited:
        visited.add(cursor)
        r = pages[cursor]
        source_slots += min(15 - cursor, len(r["body"].get("comments") or []))
        for value in comments(r["body"], aid):
            if value["platform_comment_id"] not in seen and len(rows) < 15:
                seen.add(value["platform_comment_id"])
                rows.append({**value, "sample_position": len(rows)})
        selected.append(r)
        next_cursor = r["body"].get("cursor")
        finished = (
            len(rows) == 15
            or source_slots >= 15
            or r["body"].get("has_more") == 0
            or (type(next_cursor) is int and next_cursor >= 15)
        )
        if finished:
            break
        next_cursor = r["body"].get("cursor")
        if type(next_cursor) is not int or next_cursor <= cursor or next_cursor >= 15:
            break
        cursor = next_cursor
    return {
        "aweme_id": aid,
        "comments": rows,
        "episode_response": episode,
        "comment_responses": selected,
        "sample_complete": finished,
    }


@contextmanager
def exclusive_profile():
    SESSION.mkdir(parents=True, exist_ok=True)
    os.chmod(SESSION, 0o700)
    fd = os.open(SESSION / "profile.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AdapterError("SOURCE_UNAVAILABLE") from None
        yield


async def open_context(playwright, *, headless):
    profile = SESSION / "profile"
    profile.mkdir(exist_ok=True)
    os.chmod(profile, 0o700)
    return await playwright.chromium.launch_persistent_context(
        str(profile),
        headless=headless,
        viewport={"width": 1280, "height": 900},
        accept_downloads=False,
    )


async def capture_page(context, series_id, uid, *, timeout=35, before_request=None):
    if not series_id.isascii() or not series_id.isdecimal():
        raise AdapterError("INVALID_INPUT")
    page = await context.new_page()
    responses, diagnostics, jobs, ready = [], [], set(), asyncio.Event()
    safe_error = None

    async def route(request):
        nonlocal safe_error
        u = urlsplit(request.request.url)
        q = dict(parse_qsl(u.query))
        if safe_error:
            await request.abort()
            return
        if (
            before_request
            and u.hostname == "www.douyin.com"
            and (u.path in (EPISODES, COMMENTS) or request.request.resource_type == "document")
        ):
            from app.security.errors import Denied
            from app.tasks.service import TaskError

            try:
                before_request()
            except (TaskError, Denied) as exc:
                safe_error = exc.code if isinstance(exc, TaskError) else "ACCESS_REVOKED"
                ready.set()
                await request.abort()
                return
        if request.request.resource_type == "media" or (
            u.hostname == "www.douyin.com"
            and u.path == COMMENTS
            and q.get("cursor", "0").isdecimal()
            and int(q.get("cursor", "0")) >= 15
        ):
            await request.abort()
        else:
            await request.continue_()

    async def receive(response):
        nonlocal safe_error
        u = urlsplit(response.url)
        if u.hostname != "www.douyin.com" or u.path not in (EPISODES, COMMENTS):
            return
        q = dict(parse_qsl(u.query))
        if u.path == EPISODES and q.get("series_id") != series_id:
            return
        diagnostics.append({"path": u.path, "status": response.status})
        if response.status in (403, 429):
            safe_error = "SOURCE_UNAVAILABLE"
            ready.set()
            return
        try:
            body = await response.body()
            if len(body) > 4 * 1024 * 1024:
                return
            data = json.loads(body)
            responses.append(
                {
                    "path": u.path,
                    "parameters": {
                        k: q[k] for k in ("series_id", "aweme_id", "cursor", "count") if k in q
                    },
                    "status": response.status,
                    "body": data,
                    "captured_at": datetime.now(UTC).isoformat(),
                }
            )
            bundle = sample_bundle(responses, series_id, uid)
            if bundle["sample_complete"]:
                ready.set()
        except (ValueError, TypeError, AdapterError):
            return

    def schedule(response):
        job = asyncio.create_task(receive(response))
        jobs.add(job)
        job.add_done_callback(jobs.discard)

    await page.route("**/*", route)
    page.on("response", schedule)
    try:
        from playwright.async_api import Error as BrowserError

        try:
            navigation = await page.goto(
                f"https://www.douyin.com/collection/{series_id}/1",
                wait_until="domcontentloaded",
                timeout=35000,
            )
            if navigation:
                diagnostics.append(
                    {"path": urlsplit(navigation.url).path, "status": navigation.status}
                )
                if navigation.status in (403, 429):
                    safe_error = "SOURCE_UNAVAILABLE"
                    ready.set()
        except BrowserError:
            safe_error = safe_error or "FETCH_FAILED"
            ready.set()
        try:
            await asyncio.wait_for(ready.wait(), timeout)
        except TimeoutError:
            pass
        if jobs:
            await asyncio.gather(*list(jobs), return_exceptions=True)
        try:
            result = sample_bundle(responses, series_id, uid)
        except (AdapterError, ValueError, TypeError):
            result = {
                "aweme_id": None,
                "comments": [],
                "episode_response": None,
                "comment_responses": [],
                "sample_complete": False,
            }
        result.update(
            series_id=series_id,
            uid=uid,
            captured_at=datetime.now(UTC).isoformat(),
            method="dedicated_browser_network_json",
            status="sampled"
            if (result["sample_complete"] or result["comments"]) and not safe_error
            else "session_not_ready",
            diagnostics=diagnostics,
            landing_path=urlsplit(page.url).path,
            safe_error=safe_error,
        )
        return result
    finally:
        page.remove_listener("response", schedule)
        await page.close()
        if jobs:
            await asyncio.gather(*list(jobs), return_exceptions=True)


async def guarded_capture(
    context, series_id, uid, *, before_request=None, on_request=None, timeout=35
):
    """One serial page visit, sharing the public connector's persistent cooldown."""
    directory = ROOT / "public-series"
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "request-gate.json", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "r+") as gate:
        try:
            fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AdapterError("SOURCE_UNAVAILABLE") from None
        state = json.loads(gate.read() or "{}")
        if state.get("blocked_until", 0) > time.time():
            raise AdapterError("SOURCE_UNAVAILABLE")
        if before_request:
            before_request()
        await asyncio.sleep(max(0, 10 - (time.time() - state.get("last_request", 0))))
        if before_request:
            before_request()
        if on_request:
            on_request()
        state["last_request"] = time.time()

        def save():
            gate.seek(0)
            json.dump(state, gate)
            gate.truncate()
            gate.flush()
            os.fsync(gate.fileno())

        save()
        result = await capture_page(
            context, series_id, uid, timeout=timeout, before_request=before_request
        )
        statuses = [r["status"] for r in result.get("diagnostics", [])]
        if any(s in (403, 429) for s in statuses):
            state.update(blocked_until=time.time() + 86400)
            save()
        return result


async def prepare(series_id):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BINARIES))
    from playwright.async_api import async_playwright

    with exclusive_profile():
        async with async_playwright() as p:
            context = await open_context(p, headless=False)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(
                    f"https://www.douyin.com/collection/{series_id}/1",
                    wait_until="domcontentloaded",
                )
                print(
                    "独立采集窗口已打开。仅在此窗口完成登录；关闭窗口后保存独立会话。", flush=True
                )
                await page.wait_for_event("close", timeout=0)
            finally:
                await context.close()


async def prepare_search_verification():
    """Human-operated session maintenance only: no collection, solving or gate reset."""
    from playwright.async_api import async_playwright

    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BINARIES))
    with exclusive_profile():
        async with async_playwright() as p:
            context = await open_context(p, headless=False)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(
                    "https://www.douyin.com/search/%E5%BE%AE%E7%94%B5%E5%BD%B1?type=video&sort_type=0",
                    wait_until="domcontentloaded", timeout=35000,
                )
                print("独立采集窗口已打开：请在原网页人工完成验证或登录；如已正常显示搜索页，直接关闭此窗口。没有启动批量采集，也没有解除原冷却。", flush=True)
                await page.wait_for_event("close", timeout=0)
            finally:
                await context.close()
                print("独立会话窗口已关闭；会话已保存，尚未自动判定验证成功或恢复采集。", flush=True)
