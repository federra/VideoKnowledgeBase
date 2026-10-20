from datetime import UTC, datetime


def test_shanghai_business_date_at_midnight():
    from app.intelligence.service import shanghai_date

    assert str(shanghai_date(datetime(2026, 10, 16, 15, 59, 59, tzinfo=UTC))) == "2026-10-16"
    assert str(shanghai_date(datetime(2026, 10, 16, 16, 0, tzinfo=UTC))) == "2026-10-17"


def test_feed_contract_accepts_explicit_provider_default_order():
    from app.contracts.models import IntelligenceFeed

    result = IntelligenceFeed.model_validate(
        {
            "business_code": "motion_comic",
            "business_date": "2026-10-17",
            "has_snapshot": True,
            "metrics": {"videos": "10", "creators": None, "comments": None, "likes": None},
            "boards": [],
            "creators": [],
            "page": 1,
            "page_size": 10,
            "total": "10",
            "items": [],
            "keyword_ranking_status": "default_order",
        }
    )
    assert result.keyword_ranking_status == "default_order"
