"""One first-page comment-response capture. Inner data shape is intentionally unassumed."""

import json
import re
from datetime import UTC, datetime
from time import monotonic

import httpx

from app.connectors.redfox import AdapterError, Reply, safe_evidence

CAPABILITY = "douyin.comments.capture"
VERSION = "tikhub-comments-capture-v1"
URL = "https://api.tikhub.io/api/v1/douyin/app/v3/fetch_video_comments"
MAX_RESPONSE = 1024 * 1024


class TikHub:
    url = URL

    def __init__(self, key, *, transport=None):
        self.key, self.transport = key, transport

    def ready(self):
        value = self.key()
        if not isinstance(value, str) or not value.strip():
            raise AdapterError("SOURCE_UNAVAILABLE")
        return value

    def fetch(self, capability, request, *, maximum):
        if (
            capability != CAPABILITY
            or maximum != 20
            or set(request) != {"aweme_id", "cursor", "count"}
            or request["cursor"] != 0
            or request["count"] != 20
            or type(request["count"]) is not int
            or type(request["cursor"]) is not int
            or not isinstance(request["aweme_id"], str)
            or not re.fullmatch(r"[0-9]{1,32}", request["aweme_id"])
        ):
            raise AdapterError("INVALID_INPUT")
        return self._fetch(request)

    def _fetch(self, request):
        key = self.ready()
        body, status, provider_code = bytearray(), None, None
        outcome, error = "network_error", "EXTERNAL_RESULT_UNKNOWN"
        try:
            with (
                httpx.Client(
                    transport=self.transport,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=httpx.Timeout(60, connect=10),
                ) as client,
                client.stream(
                    "GET", self.url, params=request, headers={"Authorization": "Bearer " + key}
                ) as response,
            ):
                status = response.status_code
                started = monotonic()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > MAX_RESPONSE or monotonic() - started > 120:
                        outcome, error = "invalid_shape", "INVALID_RESPONSE"
                        break
                    body.extend(chunk)
                else:
                    if status != 200:
                        outcome, error = "http_error", "SOURCE_UNAVAILABLE"
                    else:
                        try:
                            data = json.loads(body)
                            if not isinstance(data, dict) or type(data.get("code")) is not int:
                                raise ValueError()
                            provider_code = str(data["code"])
                            if data["code"] != 200:
                                outcome, error = "provider_error", "SOURCE_UNAVAILABLE"
                            elif "data" not in data:
                                raise ValueError()
                            else:
                                outcome, error = "success", None
                        except (ValueError, TypeError):
                            outcome, error = "invalid_shape", "INVALID_RESPONSE"
        except httpx.RequestError:
            # Exceptions may contain the credential-bearing URL; never stringify them.
            pass
        raw_text = safe_evidence(bytes(body) or b'{"response_unavailable":true}', key)
        return Reply(status, provider_code, outcome, raw_text, datetime.now(UTC), error=error)
