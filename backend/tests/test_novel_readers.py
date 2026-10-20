"""Reader units must become exact integer counts before ranking."""

import pytest

from app.connectors.redfox import AdapterError


@pytest.mark.parametrize(
    "value,expected",
    [("9.6万", 96000), ("32.6万", 326000), ("1.2亿", 120000000),
     ("9.6千", 9600), ("96,000人在读", 96000), ("0", 0), (0, 0),
     ("326000", 326000), (" 32.6 万人 ", 326000), (None, None), ("—", None)],
)
def test_reader_numbers_are_exact_and_missing_is_not_zero(value, expected):
    from app.connectors.novel_metrics import reader_number

    assert reader_number(value) == expected


@pytest.mark.parametrize("value", [True, -1, "32.6", "9.6万+", "未知文本", "0.00001万", "9223372036854775808", "0.99999999999999999999999999999999999999"])
def test_reader_numbers_reject_ambiguous_fractional_or_overflow_counts(value):
    from app.connectors.novel_metrics import reader_number

    with pytest.raises(AdapterError):
        reader_number(value)


def test_fanqie_normalization_converts_readers_without_touching_source_rank():
    from app.connectors.novels import normalize
    from tests.test_novels import board

    batch = normalize(board(), {"code": 0, "data": {"book_list": [
        {"bookId": "1", "bookName": "甲", "read_count": "9.6万", "currentPos": 1},
        {"bookId": "2", "bookName": "乙", "read_count": "32.6万", "currentPos": 2},
    ]}}, decoder={})
    assert [r["content"]["source_tags"][0]["reader_count"] for r in batch.records] == [96000, 326000]
    assert [r["provider_rank"] for r in batch.records] == [1, 2]
