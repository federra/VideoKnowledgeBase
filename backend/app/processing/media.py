"""Bounded local container probing. No URL input, ASR, OCR or invented transcript."""

import io
import json
import shutil
import subprocess
import wave
from decimal import Decimal, InvalidOperation

from app.tasks.service import TaskError


def probe_media(body, media_type):
    if media_type == "audio/wav":
        try:
            with wave.open(io.BytesIO(body), "rb") as audio:
                frames = audio.getnframes()
                rate = audio.getframerate()
                size = frames * audio.getnchannels() * audio.getsampwidth()
                if (
                    not rate
                    or not frames
                    or size > 64 * 1024 * 1024
                    or len(audio.readframes(frames)) != size
                ):
                    raise ValueError()
                duration = frames * 1000 // rate
                if duration > 7200000:
                    raise ValueError()
                return {"media_kind": "audio", "duration_ms": duration}
        except (wave.Error, EOFError, ValueError):
            raise TaskError("INVALID_RESPONSE") from None
    executable = shutil.which("ffprobe")
    if not executable:
        raise TaskError("INSUFFICIENT_MATERIAL")
    if len(body) > 64 * 1024 * 1024:
        raise TaskError("INVALID_INPUT")
    try:
        result = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-protocol_whitelist",
                "pipe",
                "-i",
                "pipe:0",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
            ],
            input=body,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
        if result.returncode or len(result.stdout) > 16384:
            raise ValueError()
        info = json.loads(result.stdout)
        kinds = {s["codec_type"] for s in info["streams"]}
        expected = "video" if media_type == "video/mp4" else "audio"
        if expected not in kinds:
            raise ValueError()
        seconds = Decimal(info.get("format", {}).get("duration", "NaN"))
        if not seconds.is_finite() or seconds <= 0 or seconds > 7200:
            raise ValueError()
        return {"media_kind": expected, "duration_ms": int(seconds * 1000)}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, InvalidOperation):
        raise TaskError("INVALID_RESPONSE") from None
