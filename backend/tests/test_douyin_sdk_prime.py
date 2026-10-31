import json
from app.connectors import douyin_search_session as ss


def test_resume_primes_native_sdk_without_repeating_successful_first_api(tmp_path, monkeypatch):
    from app.connectors.douyin_sdk_prime import prime
    monkeypatch.setattr(ss, 'ROOT', tmp_path)
    source = ss.SearchSession()
    seen = []

    class Request:
        resource_type = 'fetch'
        url = 'https://www.douyin.com/aweme/v1/web/search/item/?keyword=%E5%BE%AE%E7%94%B5%E5%BD%B1&search_channel=aweme_video_web&offset=0&count=16'
        headers = {'uifid': 'same-native-session', 'cookie': 'never-copy'}
        def is_navigation_request(self): return False

    class Route:
        request = Request()
        def abort(self): seen.append('blocked-first-api')
        def continue_(self): raise AssertionError('successful first API must not be fetched twice')

    class Response:
        status = 200
        def body(self): return b'<html><title>Search</title></html>'

    class Page:
        def route(self, pattern, callback): self.route_fn = callback
        def on(self, *args): pass
        def goto(self, *args, **kwargs): self.route_fn(Route()); return Response()
        def unroute(self, *args): pass
        def remove_listener(self, *args): pass

    source.ctx = type('Context', (), {'new_page': lambda self: Page()})()
    result = prime(source, 'search', '微电影', private_root=tmp_path)
    assert result['status'] == 200 and result.get('error') is None
    assert seen == ['blocked-first-api']
    assert source.template['offset'] == '0'
    assert source.native_headers == {'uifid': 'same-native-session'}
    assert source.page_key == ('search', '微电影')
    assert 'same-native-session' not in json.dumps(result)
