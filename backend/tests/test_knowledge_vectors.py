"""Vector interface validation; test vectors never imply semantic model quality."""

import pytest


@pytest.mark.parametrize(
    "value", [[0.0, 0.0], [1.0], [float("nan"), 1.0], [True, 1.0], [float("inf"), 1.0]]
)
def test_invalid_embedding_rejected(value):
    from app.knowledge.vectors import checked_vector

    with pytest.raises(ValueError):
        checked_vector(value, 2)


def test_embedding_chunks_preserve_offsets_and_complete_text():
    from app.knowledge.vectors import checked_vector, chunks

    text = "人物发现线索后改变行动。" * 200
    parts = chunks(text)
    assert "".join(text[a:b] for a, b in parts) == text
    assert all(0 < b - a <= 800 for a, b in parts)
    assert checked_vector([1, 2], 2) == [1.0, 2.0]
