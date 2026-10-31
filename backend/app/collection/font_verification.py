"""Verify the public Fanqie font against the existing exact outline map."""

import hashlib
import re
from urllib.parse import urlsplit

import httpx

from app.connectors.fontcodec import spec


def font_urls(text):
    urls = []
    for block in re.findall(r"@font-face\s*\{[^}]+\}", text):
        if re.search(r"font-weight\s*:\s*400\b", block):
            urls += re.findall(
                r"https://lf6-awef\.bytetos\.com/obj/awesome-font/[^)\s\'\"]+\.otf",
                block,
            )
    return list(dict.fromkeys(urls))


def verify_font(html, directory, *, checkpoint=lambda: None):
    """Read styles referenced by the captured page; require the exact approved 400-weight font."""
    styles = re.findall(r"<link[^>]+href=[\'\"]([^\'\"]+\.css)[\'\"]", html)
    reads = []
    fonts = font_urls(html)
    with httpx.Client(timeout=25, follow_redirects=False) as client:

        def read(url, host):
            checkpoint()
            if urlsplit(url).scheme != "https" or urlsplit(url).hostname != host:
                raise RuntimeError("Untrusted metadata host")
            with client.stream("GET", url) as r:
                r.raise_for_status()
                data = b""
                for chunk in r.iter_bytes():
                    data += chunk
                    if len(data) > 3 * 1024 * 1024:
                        raise RuntimeError("Metadata too large")
            reads.append(
                {
                    "url": url,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            )
            return data

        if not fonts:
            for href in styles[:8]:
                url = "https:" + href if href.startswith("//") else href
                css = read(url, "lf-fe.fqnovelstatic.com").decode("utf-8")
                fonts += font_urls(css)
        fonts = list(dict.fromkeys(fonts))
        if not fonts:
            raise RuntimeError("Current font not discovered; no book calls")
        if len(fonts) != 1:
            raise RuntimeError("Ambiguous content fonts; no book calls")
        approved = spec()["font_sha256"]
        found = False
        for url in fonts:
            data = read(url, "lf6-awef.bytetos.com")
            sha = hashlib.sha256(data).hexdigest()
            if sha == approved:
                (directory / (sha + ".otf")).write_bytes(data)
                found = True
        if not found:
            raise RuntimeError("Font changed; rebuild exact outline map before importing")
    return reads
