import json
import time

import pytest

from app.connectors import douyin_posts_http as posts_http
from app.connectors import douyin_search_session as ss
from tests.test_douyin_search import wrapped


def test_malformed_received_json_is_retained_as_failure_evidence(monkeypatch):
    source = ss.SearchSession()
    value = wrapped([])
    value["body"]["data"] = [None]
    raw = json.dumps(value)
    monkeypatch.setattr(source, "_guard", lambda op: {"status": 200, "raw": raw})
    result = source.fetch("search")
    assert result.error == "INVALID_RESPONSE"
    assert result.raw_text == raw


def test_sdk_detail_restriction_is_cooldown_and_stops_comment_request(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "ROOT", tmp_path)
    source = ss.SearchSession()
    requests = []

    class Request:
        resource_type = "fetch"

        def __init__(self, path):
            self.url = "https://www.douyin.com" + path + "?aweme_id=111&cursor=0"

        def is_navigation_request(self):
            return False

    class Route:
        def __init__(self, path):
            self.request = Request(path)
            self.allowed = None

        def abort(self):
            self.allowed = False

        def continue_(self):
            self.allowed = True

    class Response:
        status = 403
        url = "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=111"

        def body(self):
            return b"Forbidden"

    class Page:
        def route(self, pattern, fn):
            self.route_fn = fn

        def on(self, event, fn):
            self.receive = fn

        def goto(self, *a, **kw):
            r = Route("/aweme/v1/web/aweme/detail/")
            self.route_fn(r)
            requests.append(r)
            self.receive(Response())
            r = Route(ss.COMMENTS)
            self.route_fn(r)
            requests.append(r)
            return type("Document", (), {"status": 200})()

        def wait_for_timeout(self, *a):
            pass

        def unroute(self, *a):
            pass

        def remove_listener(self, *a):
            pass

    source.ctx = type("Context", (), {"new_page": lambda self: Page()})()
    ticks = iter([0, 36, 37])
    monkeypatch.setattr(ss.time, "monotonic", lambda: next(ticks))
    result = source.fetch("comments", "111")
    assert result.http_status == 403
    assert requests[0].allowed is True and requests[1].allowed is False
    assert (
        json.loads((tmp_path / "public-series/request-gate.json").read_text())["blocked_until"]
        > time.time()
    )


def test_http200_challenge_stops_before_api_wait_and_keeps_safe_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "ROOT", tmp_path)
    source = ss.SearchSession(one_off_retry=True)
    html = '<html><title>验证码中间页</title><script src="https://lf-cdn-tos.bytescm.com/obj/static/sec_sdk_build/3.5.2/captcha/index.js"></script><script>var private_challenge="do-not-log";</script></html>'

    class Response:
        status = 200
        url = "https://www.douyin.com/search/%E5%BE%AE%E7%94%B5%E5%BD%B1?type=video&sort_type=0"

        def body(self):
            return html.encode()

    class Page:
        def route(self, *a):
            pass

        def on(self, *a):
            pass

        def goto(self, *a, **k):
            return Response()

        def wait_for_timeout(self, *a):
            raise AssertionError("challenge must not wait for business API")

        def unroute(self, *a):
            pass

        def remove_listener(self, *a):
            pass

    source.ctx = type("Context", (), {"new_page": lambda self: Page()})()
    reply = source.fetch("search")
    assert reply.http_status == 200
    assert reply.error == "SOURCE_VERIFICATION_REQUIRED"
    assert "do-not-log" not in reply.raw_text
    assert "验证码中间页" in reply.raw_text
    gate = json.loads((tmp_path / "public-series/request-gate.json").read_text())
    assert gate["verification_required"] is True
    assert "blocked_until" not in gate
    again = source.fetch("search")
    assert again.error == "SOURCE_VERIFICATION_REQUIRED"


def test_challenge_words_inside_a_normal_result_do_not_require_verification():
    from app.connectors.douyin_verification import challenge_metadata
    assert challenge_metadata(b'<html><title>Normal search</title><p>captcha/index.js</p></html>') is None


def test_private_capture_io_failure_does_not_hide_human_verification(tmp_path,monkeypatch):
    from app.connectors import douyin_verification as dv
    body='<title>验证码中间页</title><script src="https://lf-cdn-tos.bytescm.com/obj/static/sec_sdk_build/3.5.2/captcha/index.js"></script>'.encode()
    def unavailable(*args,**kwargs):raise OSError('private failure text')
    monkeypatch.setattr(dv.os,'open',unavailable)
    info=dv.retain_challenge(body,tmp_path/'verification')
    assert info['requires_human'] and info['private_document_saved'] is False
    assert 'private failure text' not in str(info)


def test_comment_continuation_uses_initialized_page_and_sdk():
    """A nonzero cursor must retain the page where the website installed its SDK."""
    source = ss.SearchSession()

    class Response:
        status = 200
        url = 'https://www.douyin.com/aweme/v1/web/comment/list/?aweme_id=111&cursor=5&count=5'

        def body(self):
            return json.dumps({'status_code': 0, 'comments': [], 'has_more': 0, 'cursor': 5}).encode()

    class Page:
        def close(self):
            raise AssertionError('must preserve initialized comment page for continuation')

        def route(self, pattern, callback):
            pass

        def on(self, event, callback):
            self.receive = callback

        def evaluate(self, script, url):
            assert 'cursor=5' in url['url']
            assert 'count=10' in url['url']  # Five already received; never request beyond 15 slots.
            self.receive(Response())

        def unroute(self, *args):
            pass

        def remove_listener(self, *args):
            pass

    source.page = Page()
    result = source._capture('comments', '111', 5, '')
    value = json.loads(result['raw'])
    assert result['status'] == 200
    assert value['parameters']['cursor'] == '5'
    assert value['body']['has_more'] == 0


def test_search_continuation_preserves_genuine_native_uifid_header():
    source = ss.SearchSession()
    source.template = {'keyword': '微电影', 'search_channel': 'aweme_video_web', 'offset': '16'}
    source.template_path = '/aweme/v1/web/search/item/'
    source.native_headers = {'uifid': 'native-session-value'}

    class Response:
        status = 200
        url = 'https://www.douyin.com/aweme/v1/web/search/item/?keyword=%E5%BE%AE%E7%94%B5%E5%BD%B1&search_channel=aweme_video_web&offset=36&search_id=chain'
        def body(self):
            return json.dumps({'status_code':0,'data':[],'has_more':0,'cursor':36}).encode()

    class Page:
        def route(self, *args):
            pass
        def on(self, event, callback):
            self.receive = callback
        def evaluate(self, script, payload):
            assert payload['headers'] == {'uifid':'native-session-value'}
            assert 'setRequestHeader' in script
            self.receive(Response())
        def unroute(self, *args):
            pass
        def remove_listener(self, *args):
            pass

    source.page = Page()
    result = source._capture('search','微电影',36,'chain')
    assert result['status'] == 200
    assert json.loads(result['raw'])['parameters']['offset'] == '36'


def test_explicit_headed_search_does_not_enable_retry_exception():
    source = ss.SearchSession(headless=False)
    assert source.headless is False and source.one_off_retry is False


def test_explicit_xhr_retains_body_when_response_event_resource_is_unavailable(monkeypatch):
    source = ss.SearchSession()
    source.template = {'keyword':'微电影','search_channel':'aweme_video_web'}
    source.template_path = '/aweme/v1/web/search/item/'

    class Page:
        def route(self,*args): pass
        def on(self,*args): pass
        def evaluate(self,script,payload):
            return {'status':200,'body':'{"status_code":0,"data":[],"cursor":36,"has_more":0}',
                    'url':'https://www.douyin.com/aweme/v1/web/search/item/?keyword=%E5%BE%AE%E7%94%B5%E5%BD%B1&search_channel=aweme_video_web&offset=36&search_id=chain&a_bogus=never-log&msToken=never-log'}
        def unroute(self,*args): pass
        def remove_listener(self,*args): pass
    source.page=Page()
    ticks=iter([0,36,37])
    monkeypatch.setattr(ss.time,'monotonic',lambda:next(ticks))
    value=source._capture('search','微电影',36,'chain')
    assert value['status']==200
    parsed=json.loads(value['raw'])
    assert parsed['body']['cursor']==36
    assert 'never-log' not in value['raw']


def test_comment_api_uses_initialized_official_sdk_without_opening_video_pages():
    source = ss.SearchSession()
    source.native_headers = {'uifid':'genuine-same-session'}
    calls=[]

    class Page:
        url='https://www.douyin.com/search/%E5%BE%AE%E7%94%B5%E5%BD%B1?type=video'
        def close(self): raise AssertionError('keep initialized same-origin SDK')
        def route(self,*args): pass
        def on(self,*args): pass
        def evaluate(self,script,payload):
            calls.append(payload)
            assert 'count=15' in payload['url']
            assert payload['headers']=={'uifid':'genuine-same-session'}
            return {'status':200,'url':payload['url'],'body':'{"status_code":0,"comments":[],"has_more":0,"cursor":0}'}
        def unroute(self,*args): pass
        def remove_listener(self,*args): pass
    source.page=Page()
    for aid in ('111','222'):
        result=source._capture('comments',aid,0,'')
        assert result['status']==200
        assert json.loads(result['raw'])['parameters']['aweme_id']==aid
    assert len(calls)==2


def test_reused_comment_prefix_can_continue_on_existing_official_sdk(monkeypatch):
    source=ss.SearchSession()
    source.page=type('Page',(),{'url':'https://www.douyin.com/search/test'})()
    source.page_key=('search','微电影')
    source.native_headers={'uifid':'same-session'}
    monkeypatch.setattr(source,'_guard',lambda action:action())
    monkeypatch.setattr(source,'_capture',lambda *args:{'status':200,'raw':json.dumps({'kind':'comments','parameters':{'aweme_id':'111','cursor':'5'},'body':{'status_code':0,'comments':[],'has_more':0,'cursor':5}})})
    assert source.fetch('comments','111',5).error is None


@pytest.mark.parametrize('module,source_class', [(ss, ss.SearchSession), (posts_http, posts_http.SessionPosts)])
def test_rate_limit_fence_crossing_deadline_never_sleeps_negative(tmp_path, monkeypatch, module, source_class):
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    gate = tmp_path / 'public-series/request-gate.json'
    gate.parent.mkdir()
    gate.write_text(json.dumps({'last_request':100}))
    now = [109.9]
    monkeypatch.setattr(module.time, 'time', lambda:now[0])
    def sleep(seconds):
        if seconds < 0:
            raise ValueError('sleep length must be non-negative')
        now[0] += seconds
    monkeypatch.setattr(module.time, 'sleep', sleep)
    source = source_class()
    source.before_request = lambda:now.__setitem__(0, 110.1)
    operations = []
    result = source._guard(lambda:operations.append(True) or {'status':200})
    assert result == {'status':200}
    assert operations == [True]
    assert json.loads(gate.read_text())['last_request'] >= 110
