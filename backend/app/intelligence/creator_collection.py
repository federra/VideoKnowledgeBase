"""Choose the business-specific monitored-creator collection policy."""


def collect_creators(channels):
    if channels.ticket.payload["business"] == "story_short":
        from app.intelligence.creator_posts import collect_creators as collect
    else:
        from app.intelligence.creator_series import collect_creators as collect
    return collect(channels)
