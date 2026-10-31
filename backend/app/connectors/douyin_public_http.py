"""Fixed public Douyin endpoints; no cookies, redirects, signing or paid fallback."""

import fcntl
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.connectors.redfox import AdapterError, Reply

HOST = "https://www.douyin.com/aweme/v1/web/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
PATHS = {"catalog": "series/list/", "episodes": "series/aweme/", "comments": "comment/list/"}


class PublicDouyin:
    def __init__(self, client=None, directory=None):
        self.client = client
        self.before_request = None
        self.directory = Path(
            directory or Path(__file__).resolve().parents[3] / "data/douyin/public-series"
        )

    def fetch(self, kind, target, cursor=0):
        if (
            kind not in PATHS
            or not isinstance(target, str)
            or not target
            or type(cursor) is not int
            or cursor < 0
        ):
            raise AdapterError("INVALID_INPUT")
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "cursor": cursor,
        }
        if kind == "catalog":
            params.update(sec_user_id=target, count=18, req_from="channel_pc_web")
        elif kind == "episodes":
            params.update(series_id=target, count=6, pull_type=2, source="playlet_homepage_hot")
        else:
            params.update(aweme_id=target, count=15, item_type=0)
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.directory / "request-gate.json", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "r+") as gate:
            fcntl.flock(gate, fcntl.LOCK_EX)
            state = json.loads(gate.read() or "{}")
            if state.get("blocked_until", 0) > time.time():
                raise AdapterError("SOURCE_UNAVAILABLE")
            time.sleep(max(0, 10 - (time.time() - state.get("last_request", 0))))
            if self.before_request:
                self.before_request()
            state["last_request"] = time.time()

            def save():
                gate.seek(0)
                json.dump(state, gate)
                gate.truncate()
                gate.flush()
                os.fsync(gate.fileno())

            save()
            raw, status, error, outcome = "[no response]", None, None, "success"
            own = self.client is None
            # A new client for every request prevents accidental cookie reuse.
            client = self.client or httpx.Client(
                timeout=25, follow_redirects=False, trust_env=False
            )
            try:
                with client.stream(
                    "GET",
                    HOST + PATHS[kind],
                    params=params,
                    headers={
                        "User-Agent": UA,
                        "Referer": "https://www.douyin.com/",
                        "Accept": "application/json",
                    },
                    follow_redirects=False,
                ) as response:
                    status = response.status_code
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 4 * 1024 * 1024:
                            raise AdapterError("INVALID_RESPONSE")
                        chunks.append(chunk)
                    raw = b"".join(chunks).decode("utf-8") or "[empty response]"
                if status != 200:
                    error, outcome = "SOURCE_UNAVAILABLE", "http_error"
                else:
                    from app.connectors.douyin_series import checked

                    checked(json.loads(raw))
            except (ValueError, UnicodeError):
                error, outcome = "INVALID_RESPONSE", "invalid_shape"
            except httpx.HTTPError:
                error, outcome = "EXTERNAL_RESULT_UNKNOWN", "network_error"
            finally:
                if own:
                    client.close()
            captured = datetime.now(UTC)
            evidence = {
                "kind": kind,
                "target": target,
                "cursor": cursor,
                "parameters": params,
                "status": status,
                "body": raw,
                "captured_at": captured.isoformat(),
                "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            }
            path = self.directory / (captured.strftime("%Y%m%dT%H%M%S%f") + "-" + kind + ".json")
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
                json.dump(evidence, file, ensure_ascii=False)
            if status in (403, 429):
                state.update(blocked_until=time.time() + 86400, blocked_http_status=status)
                save()
            return Reply(status, None, outcome, raw, captured, error=error)


def resolve(url, connector=None):
    from app.connectors.creator_profiles import canonical_profile
    from app.connectors.douyin_series import catalog_identity

    sec = canonical_profile(url).rsplit("/", 1)[-1]
    reply = (connector or PublicDouyin()).fetch("catalog", sec)
    error = reply.error
    if not error:
        try:
            catalog_identity(json.loads(reply.raw_text), sec)
        except AdapterError:
            error = "INVALID_RESPONSE"
    return {"status": reply.http_status, "body": reply.raw_text, "error": error}


def parse_identity(body, url):
    from app.connectors.douyin_series import catalog_identity

    return catalog_identity(json.loads(body), url.rsplit("/", 1)[-1])
