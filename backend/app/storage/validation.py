"""Transport format checks; accepted bytes remain untrusted and are attachment-only."""

import re
import struct
import zlib
from pathlib import PurePath

from app.security.errors import Denied

TYPES = {
    ".txt": "text/plain",
    ".md": "text/plain",
    ".srt": "text/plain",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def validate(file, name, media):
    if (
        not name
        or len(name) > 200
        or any(ord(c) < 32 for c in name)
        or "/" in name
        or "\\" in name
        or name in (".", "..")
        or name.endswith((".", " "))
    ):
        raise Denied("INVALID_FILE")
    if TYPES.get(PurePath(name).suffix.lower()) != media:
        raise Denied("INVALID_FILE")
    file.seek(0)
    body = file.read()
    file.seek(0)
    valid = False
    if media == "text/plain":
        try:
            text = body.decode("utf-8-sig")
            valid = bool(text.strip()) and not any(
                ord(c) < 32 and c not in "\r\n\t\f" for c in text
            )
            valid &= not bool(
                re.search(r"<\s*(?:!doctype|html|script|svg|iframe)\b", text, re.IGNORECASE)
            )
        except UnicodeError:
            pass
    elif media == "application/pdf":
        valid = (
            bool(re.match(rb"%PDF-[12]\.[0-9]", body[:8]))
            and b"%%EOF" in body[-1024:]
            and b"startxref" in body[-2048:]
            and len(body) > 32
        )
    elif media == "video/mp4":
        offset = 0
        boxes = []
        while offset + 8 <= len(body):
            size, kind = struct.unpack(">I4s", body[offset : offset + 8])
            header = 8
            if size == 1:
                if offset + 16 > len(body):
                    break
                size = struct.unpack(">Q", body[offset + 8 : offset + 16])[0]
                header = 16
            if size == 0:
                size = len(body) - offset
            if size < header or offset + size > len(body):
                break
            boxes.append(kind)
            offset += size
        valid = (
            offset == len(body)
            and len(body) >= 32
            and boxes[:1] == [b"ftyp"]
            and all(k in boxes for k in [b"mdat", b"moov"])
        )
    elif media == "image/png":
        offset = 8
        kinds = []
        valid = body.startswith(b"\x89PNG\r\n\x1a\n")
        while valid and offset + 12 <= len(body):
            size = struct.unpack(">I", body[offset : offset + 4])[0]
            if offset + 12 + size > len(body):
                valid = False
                break
            chunk = body[offset + 4 : offset + 8 + size]
            kind = chunk[:4]
            crc = struct.unpack(">I", body[offset + 8 + size : offset + 12 + size])[0]
            valid &= zlib.crc32(chunk) & 0xFFFFFFFF == crc
            if kind == b"IHDR":
                valid &= size == 13
                if size == 13:
                    w, h = struct.unpack(">II", chunk[4:12])
                    valid &= 0 < w <= 16384 and 0 < h <= 16384 and w * h <= 40000000
            kinds.append(kind)
            offset += size + 12
        valid &= (
            offset == len(body)
            and kinds[:1] == [b"IHDR"]
            and kinds[-1:] == [b"IEND"]
            and b"IDAT" in kinds
        )
    elif media == "image/jpeg":
        valid = body.startswith(b"\xff\xd8\xff") and body.endswith(b"\xff\xd9") and len(body) > 32
        valid &= b"\xff\xda" in body and any(
            x in body for x in [b"\xff\xc0", b"\xff\xc1", b"\xff\xc2"]
        )
    if not valid:
        raise Denied("INVALID_FILE")
    return media
