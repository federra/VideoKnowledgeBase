"""Read-only Hongguo membership, never infer genres from title/description."""

from urllib.parse import urlsplit

BOARDS = {
    "hot-drama": "红果热播榜",
    "hot-real-drama": "真人剧热播榜",
    "hot-ai-drama": "AI剧热播榜",
    "hot-comic-drama": "漫剧热播榜",
}


def filter_hongguo(rows, board, genre):
    members = []
    for value in rows:
        try:
            url = urlsplit(value["entry"]["observation"].get("original_url") or "")
        except ValueError:
            continue
        if url.scheme != "https" or url.hostname not in (
            "hongguoduanju.com",
            "www.hongguoduanju.com",
        ):
            continue
        if board and value.get("source_name") != BOARDS.get(board):
            continue
        members.append(value)
    genres = list(
        dict.fromkeys(
            tag
            for value in members
            for tag in genre_labels(value)
            if isinstance(tag, str) and tag.strip()
        )
    )
    return [value for value in members if not genre or genre in genre_labels(value)], genres


def genre_labels(value):
    return list(
        dict.fromkeys(
            [
                *value.get("genre_tags", []),
                *(
                    group["genre"]
                    for group in value.get("genre_hierarchy", [])
                    if isinstance(group, dict) and isinstance(group.get("genre"), str)
                ),
            ]
        )
    )


def filter_subgenre(rows, genre, subgenre):
    def labels(value):
        return [
            label
            for group in value.get("genre_hierarchy", [])
            if isinstance(group, dict) and (not genre or group.get("genre") == genre)
            for label in group.get("subgenres", [])
            if isinstance(label, str) and label.strip()
        ]

    options = list(dict.fromkeys(label for value in rows for label in labels(value)))
    return [value for value in rows if not subgenre or subgenre in labels(value)], options
