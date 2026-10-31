def test_quality_failures_are_explicit_client_errors():
    from app.contracts.models import ERROR_STATUS
    assert ERROR_STATUS['ORIGINALITY_RISK']==422
    assert ERROR_STATUS['RUBRIC_UNAVAILABLE']==409
