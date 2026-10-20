from datetime import UTC, datetime

import pytest


def sample():
    return {'code':200,'data':{'status_code':0,'comments':[
        {'cid':'123','aweme_id':'456','text':'期待下一集','digg_count':0,'create_time':1760000000,'user':{'nickname':'采集时昵称'}},
        {'cid':'124','aweme_id':'456','text':'  ','user':{}},
        {'cid':'123','aweme_id':'456','text':'期待下一集','digg_count':0,'create_time':1760000000,'user':{'nickname':'采集时昵称'}}]}}


def test_comment_normalization_exact_target_dedup_preserves_unknown_and_username():
    from app.collection.comment_normalize import normalize_comments
    rows=normalize_comments(sample(),'456')
    assert len(rows)==1 and rows[0]['sample_position']==0
    assert rows[0]['like_count']==0 and rows[0]['username']=='采集时昵称'
    assert rows[0]['posted_at']==datetime.fromtimestamp(1760000000,UTC)
    body=sample();body['data']['comments'][0].pop('digg_count');body['data']['comments'].pop()
    assert normalize_comments(body,'456')[0]['like_count'] is None


@pytest.mark.parametrize('case',['wrong_target','bad_timestamp','conflicting_duplicate','inner_error'])
def test_comment_normalization_rejects_unsupported_evidence(case):
    from app.collection.comment_normalize import normalize_comments
    value=sample()
    if case=='wrong_target':value['data']['comments'][0]['aweme_id']='789'
    if case=='bad_timestamp':value['data']['comments'][0]['create_time']='yesterday'
    if case=='conflicting_duplicate':value['data']['comments'][2]['text']='不同原文'
    if case=='inner_error':value['data']['status_code']=1
    with pytest.raises(ValueError):normalize_comments(value,'456')
