from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.models import AnalyzeFeedbackRequest, FeedbackAnalysisView


def test_explicit_sample_key_and_retry_identity():
    body = AnalyzeFeedbackRequest(business_code='motion_comic', business_date=date(2026,10,31), expected_sample_key='a'*64)
    assert body.retry_of is None
    with pytest.raises(ValidationError):
        AnalyzeFeedbackRequest(business_code='motion_comic',business_date='2026-10-31',expected_sample_key='missing')


def test_success_view_requires_its_own_frozen_feedback():
    value=dict(id=uuid4(),entry_id=uuid4(),snapshot_id=uuid4(),business_code='motion_comic',business_date='2026-10-31',sample_key='a'*64,state='succeeded',result_state='completed',safe_error_code=None,feedback_id=uuid4())
    assert FeedbackAnalysisView(**value).feedback_id
    with pytest.raises(ValidationError):
        FeedbackAnalysisView(**{**value,'feedback_id':None})
    with pytest.raises(ValidationError):
        FeedbackAnalysisView(**{**value,'state':'queued'})
