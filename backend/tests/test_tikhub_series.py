import httpx
import pytest


def test_series_capture_is_one_exact_first_page_get_without_cookie_or_followup():
    from app.connectors.tikhub_series import CAPABILITY, Series

    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.path == "/api/v1/douyin/web/fetch_series_aweme"
        assert dict(request.url.params) == {"offset": "0", "count": "10", "content_type": "0"}
        return httpx.Response(200, json={"code": 200, "data": {"status_code": 0, "card_list": []}})

    api = Series(lambda: "offline", transport=httpx.MockTransport(transport))
    reply = api.fetch(CAPABILITY, {"offset": 0, "count": 10, "content_type": 0}, maximum=10)
    assert reply.error is None and len(calls) == 1
    for request in [
        {"offset": 10, "count": 10, "content_type": 0},
        {"offset": 0, "count": 10, "content_type": 101},
    ]:
        with pytest.raises(ValueError):
            api.fetch(CAPABILITY, request, maximum=10)
    assert len(calls) == 1


def payload():
    return {'code':200,'data':{'status_code':0,'card_list':[
        {'aweme_id':str(900+i),'series':{'series_id':str(700+i),'series_name':f'短剧{i}','desc':f'完整剧情简介{i}\n第二段','author':{'uid':'123','nickname':'作者','total_favorited':999999},'stats':{'play_vv':100+i,'collect_vv':0 if i==0 else i},'share_info':{'share_url':f'https://www.iesdouyin.com/share/playlet/detail/{700+i}/'}}} for i in range(12)
    ]}}


def test_normalize_series_preserves_desc_and_separate_series_metrics_without_author_likes():
    from app.connectors.tikhub_series import normalize_series
    result=normalize_series(payload())
    assert len(result.records)==10 and result.view_kind=='board'
    first=result.records[0]
    assert first['platform_content_id']=='series:700' and first['display_name']=='短剧0'
    assert first['content']['description']=='完整剧情简介0\n第二段'
    assert first['content']['view_count']==100 and first['content']['collect_count']==0
    for field in ['like_count','comment_count','share_count','repost_count']:assert first['content'][field] is None
    body=payload();body['data']['card_list'][0]['series']['stats']={}
    assert normalize_series(body).records[0]['content']['view_count'] is None
