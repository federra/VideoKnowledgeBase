"""One fixed search channel using authentic SDK API responses, never page-card data."""

import fcntl
import json
import os
import time
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from app.connectors import douyin_search as ds
from app.connectors.douyin_browser_session import BINARIES, ROOT, SESSION, exclusive_profile
from app.connectors.douyin_verification import CODE as VERIFICATION_CODE
from app.connectors.douyin_verification import retain_challenge
from app.connectors.redfox import AdapterError, Reply
from app.security.errors import Denied
from app.tasks.service import TaskError

HOST = "https://www.douyin.com"
COMMENTS = "/aweme/v1/web/comment/list/"
SAFE = (
    "keyword",
    "search_channel",
    "offset",
    "count",
    "search_id",
    "sort_type",
    "filter_selected",
    "aweme_id",
    "cursor",
)


class SearchSession:
    def __init__(self, *, one_off_retry=False, headless=True):
        self.headless = headless
        self.one_off_retry = one_off_retry
        self.failures = 0
        self.before_request = None
        self.page = None
        self.template = {}
        self.template_path = None
        self.native_headers = {}
        self.page_key = None

    def __enter__(self):
        gate_path = ROOT / "public-series/request-gate.json"
        if gate_path.exists():
            with gate_path.open() as gate:
                try:
                    fcntl.flock(gate, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise AdapterError("SOURCE_UNAVAILABLE") from None
                state = json.load(gate)
                if state.get("verification_required"):
                    raise AdapterError(VERIFICATION_CODE)
                if not self.one_off_retry and state.get("blocked_until", 0) > time.time():
                    raise AdapterError("SOURCE_UNAVAILABLE")
        self.lock = exclusive_profile()
        self.lock.__enter__()
        try:
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BINARIES))
            from playwright.sync_api import sync_playwright

            self.pw = sync_playwright().start()
            self.ctx = self.pw.chromium.launch_persistent_context(
                str(SESSION / "profile"),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                accept_downloads=False,
            )
        except Exception:  # noqa: BLE001 - SDK errors may contain secret URLs
            self.lock.__exit__(None, None, None)
            raise AdapterError("SOURCE_UNAVAILABLE") from None
        return self

    def __exit__(self, *args):
        try:
            self.ctx.close()
        finally:
            self.pw.stop()
            self.lock.__exit__(*args)

    def fence(self):
        if self.before_request:
            self.before_request()

    def _guard(self, operation):
        d = ROOT / "public-series"
        d.mkdir(parents=True, exist_ok=True)
        fd = os.open(d / "request-gate.json", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "r+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AdapterError("SOURCE_UNAVAILABLE") from None
            state = json.loads(f.read() or "{}")
            if state.get("verification_required"):
                raise AdapterError(VERIFICATION_CODE)
            if state.get("blocked_until", 0) > time.time() and not (
                self.one_off_retry and self.failures < 2
            ):
                raise AdapterError("SOURCE_UNAVAILABLE")
            end = state.get("last_request", 0) + 10
            while time.time() < end:
                self.fence()
                remaining = end - time.time()
                if remaining > 0:
                    time.sleep(min(0.5, remaining))
            self.fence()
            state["last_request"] = time.time()

            def save():
                f.seek(0)
                json.dump(state, f)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())

            save()
            result = operation()
            if result.get("error") == VERIFICATION_CODE:
                state.update(verification_required=True, verification_detected_at=time.time())
                save()
            if result["status"] in (403, 429):
                state["blocked_until"] = max(state.get("blocked_until", 0), time.time() + 86400)
                save()
            return result

    def _capture(self, kind, target, cursor, search_id):
        current = urlsplit(getattr(self.page, "url", ""))
        reuse_sdk = (
            kind == "comments" and self.page is not None and bool(self.native_headers)
            and current.scheme == "https" and current.hostname == "www.douyin.com"
        )
        if self.page is not None and cursor == 0 and not reuse_sdk:
            self.native_headers = {}
            self.page.close()
            self.page = None
        if self.page is None:
            self.page = self.ctx.new_page()
        self.page_key = (kind, target)
        page = self.page
        result = None
        used = False
        restricted = False
        detail_used = False

        def route(r):
            nonlocal used, detail_used
            if restricted:
                return r.abort()
            req = r.request
            u = urlsplit(req.url)
            p = dict(parse_qsl(u.query))
            if req.resource_type in ("media", "image", "font"):
                return r.abort()
            if u.hostname == "www.douyin.com" and u.path.startswith("/aweme/"):
                search = (
                    u.path in ds.PATHS
                    and kind == "search"
                    and p.get("keyword") == "微电影"
                    and p.get("search_channel") == "aweme_video_web"
                    and p.get("offset", "0") == str(cursor)
                )
                comment = (
                    u.path == COMMENTS
                    and kind == "comments"
                    and p.get("aweme_id") == target
                    and p.get("cursor", "0") == str(cursor)
                )
                detail = (
                    kind == "comments"
                    and u.path == "/aweme/v1/web/aweme/detail/"
                    and p.get("aweme_id") == target
                )
                if search or comment:
                    if used:
                        return r.abort()
                    used = True
                    if cursor == 0:
                        native_uifid = req.headers.get("uifid")
                        self.native_headers = (
                            {"uifid": native_uifid}
                            if isinstance(native_uifid, str) and 0 < len(native_uifid) <= 4096
                            else {}
                        )
                    self.fence()
                    if search:
                        self.template = p
                        self.template_path = u.path
                    return r.continue_()
                if detail:
                    if detail_used:
                        return r.abort()
                    detail_used = True
                    self.fence()
                    return r.continue_()
                return r.abort()
            if req.is_navigation_request() and u.hostname not in ("www.douyin.com", "douyin.com"):
                return r.abort()
            return r.continue_()

        def receive(resp):
            nonlocal result, restricted
            u = urlsplit(resp.url)
            p = dict(parse_qsl(u.query))
            if (
                u.hostname == "www.douyin.com"
                and kind == "comments"
                and u.path == "/aweme/v1/web/aweme/detail/"
                and p.get("aweme_id") == target
                and resp.status in (403, 429)
            ):
                restricted = True
                try:
                    failure = resp.body()
                    text = (
                        failure.decode("utf-8")
                        if len(failure) <= 4 * 1024 * 1024
                        else "[oversize initialization response]"
                    )
                except Exception:  # noqa: BLE001 - retain status without leaking SDK URL
                    text = "[unreadable initialization response]"
                result = {"status": resp.status, "raw": text}
                return
            eligible = (
                u.path in ds.PATHS
                and kind == "search"
                and p.get("keyword") == "微电影"
                and p.get("offset", "0") == str(cursor)
            ) or (
                u.path == COMMENTS
                and kind == "comments"
                and p.get("aweme_id") == target
                and p.get("cursor", "0") == str(cursor)
            )
            if u.hostname != "www.douyin.com" or not eligible:
                return
            try:
                raw = resp.body()
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError
                body = raw.decode("utf-8")
                parsed = json.loads(body)
                result = {
                    "status": resp.status,
                    "raw": json.dumps(
                        {
                            "kind": kind,
                            "path": u.path,
                            "parameters": {k: v for k, v in p.items() if k in SAFE},
                            "body": parsed,
                            "response_text": body,
                        },
                        ensure_ascii=False,
                    ),
                }
            except (ValueError, UnicodeError):
                result = {
                    "status": resp.status,
                    "raw": locals().get("body", "[invalid JSON response]"),
                }
            except Exception:  # noqa: BLE001 - no source URLs or credentials in logs
                result = {"status": resp.status, "raw": "[unreadable response]"}

        page.route("**/*", route)
        page.on("response", receive)
        try:
            if cursor == 0 and not reuse_sdk:
                url = (
                    HOST + "/search/" + quote("微电影") + "?type=video&sort_type=0"
                    if kind == "search"
                    else HOST + "/video/" + target
                )
                response = page.goto(url, wait_until="domcontentloaded", timeout=35000)
                if response and response.status in (403, 429):
                    return {"status": response.status, "raw": "[document restricted]"}
                if response and response.status == 200:
                    try:
                        document = response.body()
                        verification = retain_challenge(document, ROOT / "verification")
                    except Exception:  # noqa: BLE001 - diagnostic failures must not expose challenge URLs
                        verification = None
                    if verification is not None:
                        restricted = True
                        return {
                            "status": 200,
                            "raw": json.dumps(verification, ensure_ascii=False),
                            "error": VERIFICATION_CODE,
                        }
            else:
                if kind == "search":
                    params = {
                        k: v
                        for k, v in self.template.items()
                        if k not in ("a_bogus", "x-secsdk-web-signature", "X-Bogus")
                    }
                    params.update(offset=str(cursor), search_id=search_id, count="20")
                    url = HOST + (self.template_path or ds.PATHS[0]) + "?" + urlencode(params)
                else:
                    url = (
                        HOST
                        + COMMENTS
                        + "?"
                        + urlencode(
                            {
                                "device_platform": "webapp",
                                "aid": 6383,
                                "aweme_id": target,
                                "cursor": cursor,
                                "count": max(1, 15 - cursor),
                                "item_type": 0,
                            }
                        )
                    )
                direct = page.evaluate(
                    """async v=>await new Promise(resolve=>{
                    const x=new XMLHttpRequest();x.open('GET',v.url,true);x.withCredentials=true;x.timeout=25000;
                    for(const [name,value] of Object.entries(v.headers)){x.setRequestHeader(name,value);}
                    x.onprogress=e=>{if(e.loaded>4194304){x.abort();resolve({status:null,body:'[oversize response]'});}};
                    x.onload=()=>resolve({status:x.status,body:x.responseText,url:x.responseURL});
                    x.onerror=()=>resolve({status:null,body:'[XHR network error]'});
                    x.ontimeout=()=>resolve({status:null,body:'[XHR timeout]'});
                    try{x.send();}catch(e){resolve({status:null,body:'[SDK send failed]',exception_type:e.name});}
                    })""",
                    {"url": url, "headers": self.native_headers},
                )
                if isinstance(direct, dict) and not restricted:
                    raw = direct.get("body", "[unreadable XHR response]")
                    if not isinstance(raw, str) or len(raw.encode()) > 4 * 1024 * 1024:
                        raise AdapterError("INVALID_RESPONSE")
                    if direct.get("url"):
                        u = urlsplit(direct["url"])
                        p = dict(parse_qsl(u.query))
                        matched = (
                            kind == "search" and u.path in ds.PATHS
                            and p.get("keyword") == "微电影" and p.get("search_channel") == "aweme_video_web"
                            and p.get("offset", "0") == str(cursor)
                        ) or (
                            kind == "comments" and u.path == COMMENTS
                            and p.get("aweme_id") == target and p.get("cursor", "0") == str(cursor)
                        )
                        if u.hostname != "www.douyin.com" or u.scheme != "https" or not matched:
                            raise AdapterError("INVALID_RESPONSE")
                        try:
                            parsed = json.loads(raw)
                        except ValueError:
                            return {"status": direct.get("status"), "raw": raw}
                        raw = json.dumps({"kind": kind, "path": u.path,
                            "parameters": {k:v for k,v in p.items() if k in SAFE},
                            "body": parsed, "response_text": raw}, ensure_ascii=False)
                    return {"status": direct.get("status"), "raw": raw}
            until = time.monotonic() + 35
            while result is None and time.monotonic() < until:
                self.fence()
                page.wait_for_timeout(250)
            return result or {"status": None, "raw": "[API response unavailable]"}
        finally:
            page.unroute("**/*", route)
            page.remove_listener("response", receive)

    def fetch(self, kind, target="微电影", cursor=0, search_id=""):
        captured = datetime.now(UTC)
        try:
            current = urlsplit(getattr(self.page, "url", ""))
            comment_sdk_ready = (kind == "comments" and bool(self.native_headers)
                and current.scheme == "https" and current.hostname == "www.douyin.com")
            if cursor > 0 and (self.page is None or self.page_key != (kind, target)) and not comment_sdk_ready:
                from app.connectors.douyin_sdk_prime import prime
                initialized = self._guard(lambda: prime(self, kind, target, private_root=ROOT))
                if initialized.get("error"):
                    return Reply(initialized["status"], None, "invalid_shape", initialized["raw"], captured, error=initialized["error"])
            result = self._guard(lambda: self._capture(kind, target, cursor, search_id))
            status, raw = result["status"], result["raw"]
            error = result.get("error") or (
                None
                if status == 200
                else "SOURCE_UNAVAILABLE"
                if status
                else "EXTERNAL_RESULT_UNKNOWN"
            )
            if not error:
                try:
                    value = json.loads(raw)
                    if kind == "search":
                        ds.search_page(value)
                    else:
                        ds.comment_page(value, target)
                except (ValueError, TypeError, KeyError, AttributeError):
                    error = "INVALID_RESPONSE"
            if error:
                self.failures += 1
            return Reply(
                status, None, "invalid_shape" if error else "success", raw, captured, error=error
            )
        except (TaskError, Denied):
            raise
        except AdapterError as exc:
            return Reply(
                None, None, "invalid_shape", "[source gate unavailable]", captured, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - signed URLs never escape
            self.failures += 1
            return Reply(
                locals().get("status"),
                None,
                "invalid_shape" if "raw" in locals() else "network_error",
                locals().get("raw", json.dumps({"kind": "sdk_failure", "exception_type": type(exc).__name__}, ensure_ascii=False)),
                captured,
                error="INVALID_RESPONSE" if "raw" in locals() else "EXTERNAL_RESULT_UNKNOWN",
            )
