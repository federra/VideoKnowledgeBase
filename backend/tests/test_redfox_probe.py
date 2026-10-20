import json

import httpx
import pytest
from scripts.probe_redfox import run_probe, summarize_response


def test_probe_requires_key_before_creating_attempt(tmp_path):
    with pytest.raises(ValueError, match='REDFOX_API_KEY'):
        run_probe(tmp_path)
    assert not (tmp_path / 'data/redfox/search-user-attempt.json').exists()


def test_probe_is_one_request_without_retry_or_pagination_and_records_no_key(tmp_path):
    (tmp_path / '.env').write_text('REDFOX_API_KEY=private-test-key\n')
    requests = []

    def reply(request):
        requests.append(request)
        assert request.url == 'https://redfox.hk/story/api/dyData/searchUser'
        assert request.headers['REDFOX_API_KEY'] == 'private-test-key'
        assert json.loads(request.content) == {'keyword': '漫剧', 'offset': 0, 'sortType': '_0'}
        return httpx.Response(200, json={
            'code': 2000, 'data': {'hasMore': True, 'list': [{'uid': '123', 'followerCount': 0}]}
        })

    result = run_probe(tmp_path, transport=httpx.MockTransport(reply))
    assert result['status'] == 'success'
    assert result['account_count'] == 1
    assert result['has_more'] is True
    assert len(requests) == 1
    assert result['can_analyze_video'] is False
    evidence = (tmp_path / 'data/redfox/search-user-attempt.json').read_text()
    assert 'private-test-key' not in evidence
    with pytest.raises(ValueError, match='already'):
        run_probe(tmp_path, transport=httpx.MockTransport(reply))
    assert len(requests) == 1


def test_probe_does_not_follow_redirects_or_forward_credentials(tmp_path):
    (tmp_path / '.env').write_text('REDFOX_API_KEY=private-test-key\n')
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': 'https://example.com/'})

    result = run_probe(tmp_path, transport=httpx.MockTransport(redirect))
    assert result['status'] == 'http_error'
    assert result['http_status'] == 302
    assert len(requests) == 1


def test_provider_success_code_with_wrong_shape_is_not_reported_as_empty_success():
    result = summarize_response(200, {'code': 2000, 'data': {'list': None}})
    assert result['status'] == 'invalid_shape'
    assert result['account_count'] is None
    assert summarize_response(200, {'code': 2000, 'data': {'list': []}})['account_count'] == 0


def test_work_probes_use_existing_samples_and_each_allow_only_one_call(tmp_path):
    (tmp_path / '.env').write_text('REDFOX_API_KEY=private-test-key\n')
    directory = tmp_path / 'data/redfox'
    directory.mkdir(parents=True)
    (directory / 'search-user-response.json').write_text(json.dumps({
        'code': 2000, 'data': {'list': [{'accountId': 'private-account',
                                      'nickname': '大米漫剧（ai漫剧）', 'awemeCount': 20}]}}))
    requests = []

    def reply(request):
        requests.append(request)
        if request.url.path.endswith('queryWorkList'):
            assert json.loads(request.content) == {'accountId': 'private-account',
                                                   'offset': 0, 'sortType': '_0'}
            return httpx.Response(200, json={'code': 2000, 'data': {'hasMore': 1, 'list': [
                {'workId': 'private-work', 'title': '作品', 'likeCount': 0}]}})
        assert request.url.path.endswith('queryWork')
        assert json.loads(request.content) == {'workId': 'private-work'}
        return httpx.Response(200, json={'code': 2000, 'data': {
            'workId': 'private-work', 'audioUrl': '', 'commentCount': 0}})

    for kind in ['work-list', 'work-detail']:
        result = run_probe(tmp_path, transport=httpx.MockTransport(reply), kind=kind)
        assert result['status'] == 'success'
        assert 'private-account' not in json.dumps(result)
        assert 'private-work' not in json.dumps(result)
        with pytest.raises(ValueError, match='already'):
            run_probe(tmp_path, transport=httpx.MockTransport(reply), kind=kind)
    assert len(requests) == 2
    assert result['has_audio_url'] is False
    assert result['can_analyze_video'] is False


def test_work_probe_refuses_missing_input_and_mismatched_detail(tmp_path):
    (tmp_path / '.env').write_text('REDFOX_API_KEY=test\n')
    with pytest.raises(ValueError, match='sample'):
        run_probe(tmp_path, kind='work-detail')
    directory = tmp_path / 'data/redfox'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'work-list-response.json').write_text(json.dumps({
        'code': 2000, 'data': {'list': [{'workId': 'expected'}]}}))
    result = run_probe(tmp_path, kind='work-detail', transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={'code': 2000, 'data': {'workId': 'wrong'}})))
    assert result['status'] == 'invalid_shape'


def test_failed_work_list_cannot_trigger_detail_or_repeat_paid_call(tmp_path):
    (tmp_path / '.env').write_text('REDFOX_API_KEY=private-test-key\n')
    directory = tmp_path / 'data/redfox'
    directory.mkdir(parents=True)
    (directory / 'search-user-response.json').write_text(json.dumps({
        'code': 2000, 'data': {'list': [{'accountId': 'test-account',
                                      'nickname': '大米漫剧（ai漫剧）', 'awemeCount': 20}]}}))
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'code': 3203, 'msg': 'not collected'})

    transport = httpx.MockTransport(reply)
    result = run_probe(tmp_path, transport=transport, kind='work-list')
    assert result['status'] == 'provider_error'
    assert result['work_count'] is None
    with pytest.raises(ValueError, match='already'):
        run_probe(tmp_path, transport=transport, kind='work-list')
    with pytest.raises(ValueError, match='sample'):
        run_probe(tmp_path, transport=transport, kind='work-detail')
    assert len(requests) == 1
    assert not (directory / 'work-detail-attempt.json').exists()


def test_broad_sample_uses_uid_and_page_size_one_with_independent_receipt(tmp_path):
    (tmp_path / '.env').write_text('REDFOX_API_KEY=private-test-key\n')
    directory = tmp_path / 'data/redfox'
    directory.mkdir(parents=True)
    (directory / 'search-user-response.json').write_text(json.dumps({
        'code': 2000, 'data': {'list': [{'uid': 'private-uid',
                                      'nickname': '大米漫剧（ai漫剧）', 'awemeCount': 20}]}}))
    (directory / 'work-list-attempt.json').write_text('{"status":"provider_error"}')
    requests = []

    def reply(request):
        requests.append(request)
        assert request.url.path == '/story/api/dy/data/listWorkByAccount'
        assert json.loads(request.content) == {'userId': 'private-uid',
                                               'pageNum': 1, 'pageSize': 1}
        return httpx.Response(200, json={'code': 2000, 'data': {'total': 100, 'list': [
            {'videoId': 'private-video', 'duration': 2000, 'likeCount': 0}]}})

    result = run_probe(tmp_path, kind='broad-work-list', transport=httpx.MockTransport(reply))
    assert result['status'] == 'success'
    assert result['work_count'] == 1
    assert 'private-uid' not in json.dumps(result)
    with pytest.raises(ValueError, match='already'):
        run_probe(tmp_path, kind='broad-work-list', transport=httpx.MockTransport(reply))
    assert len(requests) == 1
    assert (directory / 'work-list-attempt.json').read_text() == '{"status":"provider_error"}'
