"""Fixed user-post API via the dedicated session's own SDK-signed XHR, no visual reads.

Reference only: MediaCrawler client session/pagination; DTK v5 author-post endpoint.
No upstream restricted-license code, forged gateway headers, identity rotation or retries.
"""

import fcntl
import json
import os
import time
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.connectors.douyin_browser_session import BINARIES, ROOT, SESSION, exclusive_profile
from app.connectors.douyin_series import checked
from app.connectors.redfox import AdapterError, Reply
from app.security.errors import Denied
from app.tasks.service import TaskError

HOST = "https://www.douyin.com"
POST = "/aweme/v1/web/aweme/post/"
PROFILE = "/aweme/v1/web/user/profile/other/"
LIMIT = 4 * 1024 * 1024


class SessionPosts:
    def __init__(self, *, headless=True):
        self.headless = headless
        self.before_request = None
        self.page = None
        self.sec = None
        self.template = {}
        self.native_headers = {}
        self.allowed = None
        self.profile_result = None
        self.api_started = False

    def __enter__(self):
        gate_path = ROOT / "public-series/request-gate.json"
        if gate_path.exists():
            with gate_path.open() as gate:
                try:
                    fcntl.flock(gate, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise AdapterError("SOURCE_UNAVAILABLE") from None
                if json.load(gate).get("blocked_until", 0) > time.time():
                    raise AdapterError("SOURCE_UNAVAILABLE")
        self.lock = exclusive_profile()
        self.lock.__enter__()
        try:
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BINARIES))
            from playwright.sync_api import sync_playwright

            self.playwright = sync_playwright().start()
            self.context = self.playwright.chromium.launch_persistent_context(
                str(SESSION / "profile"),
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                accept_downloads=False,
            )
        except Exception:  # noqa: BLE001 - sanitize SDK failures; never expose signed URLs
            self.lock.__exit__(None, None, None)
            raise AdapterError("SOURCE_UNAVAILABLE") from None
        return self

    def __exit__(self, *args):
        try:
            self.context.close()
        finally:
            self.playwright.stop()
            self.lock.__exit__(*args)

    def fence(self):
        if self.before_request:
            self.before_request()

    def _route(self, route):
        req = route.request
        u = urlsplit(req.url)
        if req.resource_type in ("media", "image", "font"):
            return route.abort()
        if u.hostname == "www.douyin.com" and u.path.startswith("/aweme/"):
            params = dict(parse_qsl(u.query))
            if u.path == POST and params.get("sec_user_id") == self.sec:
                if not self.template:
                    self.template = params
                    native_uifid = req.headers.get("uifid")
                    self.native_headers = (
                        {"uifid": native_uifid}
                        if isinstance(native_uifid, str) and 0 < len(native_uifid) <= 4096
                        else {}
                    )
                if self.allowed == ("posts", params.get("max_cursor")) and not self.api_started:
                    self.api_started = True
                    self.fence()
                    return route.continue_()
                return route.abort()
            if (
                u.path == PROFILE
                and params.get("sec_user_id") == self.sec
                and self.allowed == ("profile", None)
                and not self.api_started
            ):
                self.api_started = True
                self.fence()
                return route.continue_()
            return route.abort()
        # Never follow an API redirect to another document or credential endpoint.
        if req.is_navigation_request() and u.hostname not in ("www.douyin.com", "douyin.com"):
            return route.abort()
        return route.continue_()

    def _receive(self, response):
        u = urlsplit(response.url)
        if (
            u.hostname == "www.douyin.com"
            and u.path == PROFILE
            and self.allowed == ("profile", None)
        ):
            try:
                b = response.body()
                if len(b) > LIMIT:
                    raise ValueError
                self.profile_result = {
                    "status": response.status,
                    "body": b.decode("utf-8"),
                    "error": None,
                }
            except Exception:  # noqa: BLE001 - sanitize SDK failures; never expose signed URLs
                self.profile_result = {
                    "status": response.status,
                    "body": "[unreadable response]",
                    "error": "INVALID_RESPONSE",
                }

    def _prepare(self, sec, profile):
        if self.page is not None and self.sec == sec:
            return
        if self.page is not None:
            self.page.close()
        self.sec, self.template, self.api_started, self.profile_result = sec, {}, False, None
        self.native_headers = {}
        self.allowed = ("profile", None) if profile else None
        self.page = self.context.new_page()
        self.page.route("**/*", self._route)
        self.page.on("response", self._receive)
        self.fence()
        response = self.page.goto(
            HOST + "/user/" + sec, wait_until="domcontentloaded", timeout=35000
        )
        if response and response.status in (403, 429):
            self.profile_result = {
                "status": response.status,
                "body": "[document restricted]",
                "error": "SOURCE_UNAVAILABLE",
            }
            return
        until = time.monotonic() + 30
        while time.monotonic() < until:
            self.fence()
            if self.profile_result and self.profile_result["status"] in (403, 429):
                return
            if self.template and (not profile or self.profile_result):
                return
            self.page.wait_for_timeout(250)
        raise AdapterError("SOURCE_UNAVAILABLE")

    def _guard(self, operation):
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
            until = state.get("last_request", 0) + 10
            while time.time() < until:
                self.fence()
                remaining = until - time.time()
                if remaining > 0:
                    time.sleep(min(0.5, remaining))
            self.fence()
            state["last_request"] = time.time()

            def save():
                gate.seek(0)
                json.dump(state, gate)
                gate.truncate()
                gate.flush()
                os.fsync(gate.fileno())

            save()
            result = operation()
            if result["status"] in (403, 429):
                state["blocked_until"] = time.time() + 86400
                save()
            return result

    def resolve(self, url):
        sec = url.rsplit("/", 1)[-1]

        def operation():
            self._prepare(sec, True)
            return self.profile_result or {
                "status": None,
                "body": "[profile unavailable]",
                "error": "SOURCE_UNAVAILABLE",
            }

        try:
            result = self._guard(operation)
        except AdapterError as e:
            return {"status": None, "body": "[session unavailable]", "error": str(e)}
        if result["status"] != 200:
            result["error"] = "SOURCE_UNAVAILABLE"
        return result

    def fetch(self, sec, cursor):
        def operation():
            self._prepare(sec, False)
            if self.profile_result and self.profile_result["status"] in (403, 429):
                return self.profile_result
            q = {
                k: v
                for k, v in self.template.items()
                if k not in ("a_bogus", "X-Bogus", "x-secsdk-web-signature")
            }
            q.update(sec_user_id=sec, max_cursor=str(cursor), count="20")
            self.allowed, self.api_started = ("posts", str(cursor)), False
            # The website SDK signs its own XHR. No DOM, scrolling, OCR or manual card reads.
            return self.page.evaluate(
                """async v=>await new Promise(resolve=>{
              const x=new XMLHttpRequest();x.open('GET',v.url,true);x.withCredentials=true;x.timeout=25000;
              for(const [name,value] of Object.entries(v.headers)){x.setRequestHeader(name,value);}
              x.onprogress=e=>{if(e.loaded>4194304){x.abort();resolve({status:null,body:'[oversize response]'});}};
              x.onload=()=>resolve({status:x.status,body:x.responseText,url:x.responseURL});
              x.onerror=()=>resolve({status:null,body:'[network error]'});
              x.ontimeout=()=>resolve({status:null,body:'[timeout]'});x.send();
            })""",
                {"url": HOST + POST + "?" + urlencode(q), "headers": self.native_headers},
            )

        captured = datetime.now(UTC)
        try:
            result = self._guard(operation)
            raw = result["body"]
            status = result["status"]
            if status != 200:
                return Reply(status, None, "http_error", raw, captured, error="SOURCE_UNAVAILABLE")
            if result.get("url") and urlsplit(result["url"]).path != POST:
                raise AdapterError("INVALID_RESPONSE")
            if len(raw.encode()) > LIMIT:
                raise AdapterError("INVALID_RESPONSE")
            checked(json.loads(raw))
            return Reply(status, None, "success", raw, captured)
        except (TaskError, Denied):
            raise
        except (ValueError, AdapterError) as exc:
            return Reply(
                locals().get("status"),
                None,
                "invalid_shape",
                locals().get("raw", "[session unavailable]"),
                captured,
                error=str(exc) if isinstance(exc, AdapterError) else "INVALID_RESPONSE",
            )
        except Exception:  # noqa: BLE001 - sanitize SDK failures; never expose signed URLs
            return Reply(
                None,
                None,
                "network_error",
                "[session request failed]",
                captured,
                error="EXTERNAL_RESULT_UNKNOWN",
            )
