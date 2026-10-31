"""Saved configuration transport: one reserved call, public pinned DNS, no redirects/retry."""

import hashlib
import ipaddress
import json
import re
import socket
from urllib.parse import urlsplit

import httpx

from app.ai.deepseek import MAX_RESPONSE, ModelError, ModelReply, tokens
from app.core.config import settings


def validate_endpoint(value):
    u = urlsplit(value)
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
        or u.port not in (None, 443)
        or "\\" in value
    ):
        raise ValueError("HTTPS public endpoint required")
    host = u.hostname.rstrip(".").lower()
    if "." not in host or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Public host required")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Public address required")
    return value.rstrip("/")


def credential(secret_ref):
    # Only explicit supported references, selected by a persisted console revision.
    return {"DEEPSEEK_KEY": settings.deepseek_key, "OPENAI_API_KEY": settings.openai_api_key}.get(
        secret_ref
    )


def credential_ready(secret_ref):
    key = credential(secret_ref)
    return bool(key and key.get_secret_value().strip())


def lookup(host):
    return list({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})


class ConfiguredModel:
    def __init__(self, *, key=None, lookup=lookup, transport=None):
        self.key = key or credential
        self.lookup = lookup
        self.transport = transport

    def complete(self, config, system, user, schema, *, reserve):
        if not all(config.get(k) for k in ("revision_id", "source_id", "connection_id")):
            raise ModelError("MODEL_NOT_CONFIGURED")
        if config.get("provider") not in ("deepseek", "openai") or config.get("retries") != 0:
            raise ModelError("MODEL_NOT_CONFIGURED")
        try:
            endpoint = validate_endpoint(config["endpoint"])
            host = urlsplit(endpoint).hostname
            addresses = self.lookup(host)
            if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
                raise ValueError()
        except (ValueError, OSError):
            raise ModelError("VALIDATION_FAILED") from None
        key = self.key(config["secret_ref"])
        if not key or not key.get_secret_value().strip():
            raise ModelError("MODEL_NOT_CONFIGURED")
        payload = {
            "model": config["model"],
            "stream": False,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": system
                    + "\n输出JSON schema："
                    + json.dumps(schema, ensure_ascii=False),
                },
                {"role": "user", "content": user},
            ],
        }
        if config.get("max_tokens") is not None:
            payload["max_tokens"] = config["max_tokens"]
        if config["provider"] == "deepseek":
            # Structured creative proposals need the final JSON. DeepSeek's
            # default thinking mode can consume the entire output allowance
            # before producing content; use its explicit non-thinking mode.
            payload["thinking"] = {"type": "disabled"}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(canonical.encode()) > 262144:
            raise ModelError("INSUFFICIENT_MATERIAL")
        sha = hashlib.sha256(canonical.encode()).hexdigest()
        url = endpoint if endpoint.endswith("/chat/completions") else endpoint + "/chat/completions"
        reserve(
            {
                "provider": config["provider"],
                "endpoint": url,
                "prompt_version": "topics.v1",
                "input_sha256": sha,
                "request": json.loads(canonical),
            }
        )
        pinned = httpx.URL(url).copy_with(host=addresses[0])
        try:
            with (
                httpx.Client(
                    transport=self.transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(config["timeout"], connect=min(10, config["timeout"])),
                ) as client,
                client.stream(
                    "POST",
                    pinned,
                    headers={"Host": host, "Authorization": "Bearer " + key.get_secret_value()},
                    extensions={"sni_hostname": host},
                    json=payload,
                ) as response,
            ):
                if response.status_code in (401, 403):
                    raise ModelError("MODEL_NOT_CONFIGURED")
                if response.status_code == 429:
                    raise ModelError("RATE_LIMITED")
                if response.status_code != 200:
                    raise ModelError("SOURCE_UNAVAILABLE")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE:
                        raise ModelError("INVALID_RESPONSE")
                    body.extend(chunk)
        except httpx.RequestError:
            raise ModelError("EXTERNAL_RESULT_UNKNOWN") from None
        text, request_id, usage = None, None, None
        try:
            data = json.loads(body)
            request_id = data.get("id")
            if not isinstance(request_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,256}", request_id
            ):
                request_id = None
            usage = data.get("usage")
            choices = data["choices"]
            if len(choices) != 1 or choices[0]["finish_reason"] != "stop":
                raise ValueError()
            text = choices[0]["message"]["content"]
            decoded = json.loads(text)
            if not isinstance(decoded, dict):
                raise TypeError()
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise ModelError(
                "INVALID_RESPONSE",
                raw_text=text if isinstance(text, str) else body.decode(errors="replace"),
                provider_request_id=request_id,
                input_tokens=tokens(usage, "prompt_tokens"),
                output_tokens=tokens(usage, "completion_tokens"),
            ) from None
        return ModelReply(
            request_id,
            sha,
            tokens(usage, "prompt_tokens"),
            tokens(usage, "completion_tokens"),
            decoded,
            text,
        )
