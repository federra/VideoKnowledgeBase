"""One public Douyin homepage read, no redirects, signatures, cookies or retries."""

import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

import httpx

LIMIT = 2 * 1024 * 1024


class ProfileError(ValueError):
    pass


def canonical_profile(value):
    try:
        u = urlsplit(value.strip())
        if (
            u.scheme != "https"
            or u.hostname not in ("www.douyin.com", "douyin.com")
            or u.username
            or u.password
            or u.port not in (None, 443)
            or not re.fullmatch(r"/user/[A-Za-z0-9_-]{3,128}/?", u.path)
        ):
            raise ValueError()
    except (ValueError, AttributeError):
        raise ProfileError("仅支持完整的 https://www.douyin.com/user/… 主页链接") from None
    return "https://www.douyin.com" + u.path.rstrip("/")


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        self.active = tag == "script" and dict(attrs).get("id") in ("RENDER_DATA", "__NEXT_DATA__")

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.blocks.append(data)


def parse_identity(text, url):
    target = canonical_profile(url).rsplit("/", 1)[-1]
    parser = Scripts()
    parser.feed(text)
    matches = {}

    def visit(node, depth=0):
        if depth > 30:
            return
        if isinstance(node, dict):
            # Only explicit profile/user nodes; a recommended video author is not proof.
            for key, user in node.items():
                if key in ("user", "userInfo", "user_info") and isinstance(user, dict):
                    sec = user.get("secUid", user.get("sec_uid"))
                    uid = user.get("uid", user.get("userId", user.get("user_id")))
                    uid = str(uid) if type(uid) is int else uid
                    if (
                        sec == target
                        and isinstance(uid, str)
                        and re.fullmatch(r"[1-9][0-9]{2,24}", uid)
                    ):
                        matches[uid] = {
                            "uid": uid,
                            "sec_uid": sec,
                            "name": str(user.get("nickname") or "")[:90],
                        }
                visit(user, depth + 1)
        elif isinstance(node, list):
            for value in node:
                visit(value, depth + 1)

    for block in parser.blocks:
        for candidate in (block, unquote(unescape(block))):
            try:
                visit(json.loads(candidate))
                break
            except (ValueError, RecursionError):
                continue
    if len(matches) != 1:
        raise ProfileError("主页未提供可核验的账号UID")
    return next(iter(matches.values()))


def resolve(url, client=None):
    url = canonical_profile(url)
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=False, trust_env=False)
    result = {"status": None, "body": "[no response]", "error": "EXTERNAL_RESULT_UNKNOWN"}
    try:
        with client.stream(
            "GET",
            url,
            follow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
        ) as response:
            result["status"] = response.status_code
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > LIMIT:
                    result.update(body="[response exceeds 2MiB limit]", error="INVALID_RESPONSE")
                    return result
                chunks.append(chunk)
            result["body"] = (
                b"".join(chunks).decode("utf-8", errors="replace").replace("\x00", "\\u0000")
                or "[empty response]"
            )
        if result["status"] != 200:
            result["error"] = "SOURCE_UNAVAILABLE"
        else:
            try:
                result["identity"] = parse_identity(result["body"], url)
                result["error"] = None
            except ProfileError:
                result["error"] = "INVALID_RESPONSE"
        return result
    except httpx.HTTPError:
        return result
    finally:
        if own:
            client.close()
