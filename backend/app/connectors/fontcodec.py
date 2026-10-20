"""Exact decomposed-outline matching against the same published font version."""

import hashlib
import json
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

from app.connectors.redfox import AdapterError

DATA = Path(__file__).parent / "data" / "fanqie-font-v1.json"


def spec():
    return json.loads(DATA.read_text())


def decode(value, mapping):
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdapterError("INVALID_RESPONSE")
    out = []
    for c in value:
        if 0xE000 <= ord(c) <= 0xF8FF:
            if str(ord(c)) not in mapping:
                raise AdapterError("SOURCE_UNAVAILABLE")
            out.append(mapping[str(ord(c))])
        else:
            out.append(c)
    return "".join(out)


def build_map(public_path, reference_path):
    """Offline rebuild only; no network, OCR or approximate character guessing."""
    public, reference = TTFont(public_path), TTFont(reference_path)

    def outline(font, name):
        glyphs = font.getGlyphSet()
        pen = DecomposingRecordingPen(glyphs)
        glyphs[name].draw(pen)
        return repr(pen.value)

    needed = {outline(public, n): cp for cp, n in public.getBestCmap().items()}
    matched = {}
    ambiguous = set()
    for cp, name in reference.getBestCmap().items():
        if not (
            0x20 <= cp <= 0x7E
            or 0x2000 <= cp <= 0x206F
            or 0x3000 <= cp <= 0x9FFF
            or 0xFF00 <= cp <= 0xFFEF
        ):
            continue
        shape = outline(reference, name)
        if shape in needed:
            key = str(needed[shape])
            if key in matched and matched[key] != chr(cp):
                ambiguous.add(key)
            matched[key] = chr(cp)
    for k in ambiguous:
        matched.pop(k, None)
    if len(matched) != len(public.getBestCmap()):
        raise AdapterError("SOURCE_UNAVAILABLE")
    return {
        "font_sha256": hashlib.sha256(Path(public_path).read_bytes()).hexdigest(),
        "reference_sha256": hashlib.sha256(Path(reference_path).read_bytes()).hexdigest(),
        "method": "exact-decomposed-outlines",
        "mapping": matched,
    }
