"""Exact novel reader counts; formatted display strings are never sort keys."""

import re
from decimal import Decimal, localcontext

from app.connectors.redfox import AdapterError


def reader_number(value):
    if value is None:
        return None
    if type(value) is int:
        number = value
    elif isinstance(value, str) and len(value) <= 80:
        text = value.strip()
        if text in ("", "-", "—", "未获取", "暂无", "未知"):
            return None
        match = re.fullmatch(
            r"((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)\s*([千万亿]?)\s*(?:人(?:在读)?|在读)?",
            text,
        )
        if not match:
            raise AdapterError("INVALID_RESPONSE")
        with localcontext() as context:
            context.prec = 100  # Exact for the bounded input, including unit expansion.
            number = Decimal(match[1].replace(",", "")) * {"": 1, "千": 1000, "万": 10000, "亿": 100000000}[match[2]]
        if number != number.to_integral_value():
            raise AdapterError("INVALID_RESPONSE")
    else:
        raise AdapterError("INVALID_RESPONSE")
    if not 0 <= number <= 9223372036854775807:
        raise AdapterError("INVALID_RESPONSE")
    return int(number)
