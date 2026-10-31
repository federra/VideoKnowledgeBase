"""Recognize the HTTP-200 challenge document; never solve or expose its tokens."""

import hashlib
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

CODE = "SOURCE_VERIFICATION_REQUIRED"
MAX_DOCUMENT = 4 * 1024 * 1024


class _Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = []
        self.captcha_sdk = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag == "script":
            src = dict(attrs).get("src") or ""
            parsed = urlsplit(src)
            if (
                parsed.hostname == "lf-cdn-tos.bytescm.com"
                and parsed.path.startswith("/obj/static/sec_sdk_build/")
                and parsed.path.endswith("/captcha/index.js")
            ):
                self.captcha_sdk = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def challenge_metadata(body: bytes):
    if len(body) > MAX_DOCUMENT:
        return None
    try:
        doc = _Document()
        doc.feed(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None
    title = "".join(doc.title).strip()
    if title != "验证码中间页" or not doc.captcha_sdk:
        return None
    return {
        "kind": "human_verification_required",
        "title": title,
        "requires_human": True,
        "document_sha256": hashlib.sha256(body).hexdigest(),
        "document_bytes": len(body),
    }


def retain_challenge(body: bytes, directory: Path):
    info = challenge_metadata(body)
    if info is None:
        return None
    name = uuid4().hex + ".html"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        with os.fdopen(
            os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as file:
            file.write(body)
    except OSError:
        return {**info, "private_document_saved": False}
    # Only metadata enters task receipts; the signed challenge remains private.
    return {**info, "private_document": name, "private_document_saved": True}
