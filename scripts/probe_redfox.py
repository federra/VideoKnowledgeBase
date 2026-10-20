"""One reserved RedFox sample call per operation; no retries or pagination."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://redfox.hk/story/api/dyData/searchUser'
REQUEST = {'keyword': '漫剧', 'offset': 0, 'sortType': '_0'}


def summarize_response(http_status: int, payload: object) -> dict:
    summary = {'http_status': http_status, 'status': 'http_error', 'account_count': None,
               'provider_code': None, 'has_more': None, 'can_analyze_video': False}
    if not 200 <= http_status < 300:
        return summary
    if not isinstance(payload, dict):
        summary['status'] = 'invalid_shape'
        return summary
    summary['provider_code'] = payload.get('code')
    if payload.get('code') != 2000:
        summary['status'] = 'provider_error'
        return summary
    data = payload.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
        summary['status'] = 'invalid_shape'
        return summary
    summary.update({'status': 'success', 'account_count': len(data['list']),
                    'has_more': data.get('hasMore'),
                    'sample_fields': sorted(data['list'][0])
                    if data['list'] and isinstance(data['list'][0], dict) else []})
    return summary


def request_plan(root: Path, kind: str) -> tuple[str, dict]:
    if kind == 'search-user':
        return ENDPOINT, REQUEST.copy()
    source = 'search-user' if kind in {'work-list', 'broad-work-list'} else 'work-list'
    try:
        sample = json.loads((root / f'data/redfox/{source}-response.json').read_text())
        if sample.get('code') != 2000:
            raise ValueError('Invalid source sample.')
        rows = sample['data']['list']
        if kind == 'broad-work-list':
            row = next(r for r in rows if r.get('nickname') == '大米漫剧（ai漫剧）'
                       and isinstance(r.get('uid'), str) and r['uid'])
            return 'https://redfox.hk/story/api/dy/data/listWorkByAccount', {
                'userId': row['uid'], 'pageNum': 1, 'pageSize': 1}
        if kind == 'work-list':
            row = next(r for r in rows if r.get('nickname') == '大米漫剧（ai漫剧）'
                       and r.get('accountId') and r.get('awemeCount', 0) > 0)
            return 'https://redfox.hk/story/api/dyData/queryWorkList', {
                'accountId': row['accountId'], 'offset': 0, 'sortType': '_0'}
        if kind == 'work-detail':
            row = next(r for r in rows if isinstance(r.get('workId'), str) and r['workId'])
            return 'https://redfox.hk/story/api/dyData/queryWork', {'workId': row['workId']}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as error:
        raise ValueError('Required source sample is missing or invalid; no call made.') from error
    raise ValueError('Unsupported probe kind.')


def summarize_content(status: int, payload: object, kind: str, request: dict) -> dict:
    if kind in {'work-list', 'broad-work-list'}:
        id_field = 'videoId' if kind == 'broad-work-list' else 'workId'
        result = summarize_response(status, payload)
        result['work_count'] = result.pop('account_count')
        if result['status'] == 'success' and any(
            not isinstance(row, dict) or not isinstance(row.get(id_field), str)
            or not row[id_field] for row in payload['data']['list']
        ):
            result['status'] = 'invalid_shape'
        return result
    result = {'http_status': status, 'status': 'http_error', 'can_analyze_video': False}
    if not 200 <= status < 300:
        return result
    if not isinstance(payload, dict):
        return {**result, 'status': 'invalid_shape'}
    result['provider_code'] = payload.get('code')
    if payload.get('code') != 2000:
        return {**result, 'status': 'provider_error'}
    data = payload.get('data')
    if not isinstance(data, dict) or data.get('workId') != request['workId']:
        return {**result, 'status': 'invalid_shape'}
    return {**result, 'status': 'success', 'sample_fields': sorted(data),
            'has_audio_url': bool(data.get('audioUrl')),
            'has_video_url': bool(data.get('videoUrl')),
            'has_comment_text': False}


def run_probe(root: Path, transport: httpx.BaseTransport | None = None,
              *, kind: str = 'search-user') -> dict:
    key = dotenv_values(root / '.env').get('REDFOX_API_KEY')
    if not key:
        raise ValueError('Configure REDFOX_API_KEY in the private project .env first.')
    endpoint, request = request_plan(root, kind)
    directory = root / 'data/redfox'
    directory.mkdir(parents=True, exist_ok=True)
    receipt = directory / f'{kind}-attempt.json'
    attempt = {'endpoint': endpoint, 'request': request, 'max_requests': 1,
               'automatic_retries': 0, 'automatic_pagination': False,
               'started_at': datetime.now(UTC).isoformat(), 'status': 'reserved'}
    try:
        descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError('A RedFox call was already reserved; inspect its receipt before any new call.') \
            from error
    with os.fdopen(descriptor, 'w') as output:
        json.dump(attempt, output, indent=2, ensure_ascii=False)
    try:
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False,
                          transport=transport) as client:
            response = client.post(endpoint, headers={'REDFOX_API_KEY': key}, json=request)
        # Keep the raw response private. Do not echo vendor messages, account data, or credentials.
        raw = response.content.replace(key.encode(), b'[REDACTED]')
        raw_descriptor = os.open(directory / f'{kind}-response.json',
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(raw_descriptor, 'wb') as output:
            output.write(raw)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            payload = None
        result = (summarize_response(response.status_code, payload) if kind == 'search-user'
                  else summarize_content(response.status_code, payload, kind, request))
    except httpx.HTTPError as error:
        result = {'status': 'network_error', 'error_type': type(error).__name__,
                  'account_count': None, 'can_analyze_video': False}
    attempt.update(result)
    attempt['completed_at'] = datetime.now(UTC).isoformat()
    receipt.write_text(json.dumps(attempt, indent=2, ensure_ascii=False) + '\n')
    if kind != 'search-user':
        return {k: v for k, v in attempt.items() if k != 'request'}
    return attempt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Show request plan without network use.')
    parser.add_argument('--kind', choices=['search-user', 'work-list', 'work-detail', 'broad-work-list'],
                        default='search-user')
    args = parser.parse_args()
    if args.dry_run:
        key_present = bool(dotenv_values(ROOT / '.env').get('REDFOX_API_KEY'))
        endpoint, request = request_plan(ROOT, args.kind)
        print(json.dumps({'endpoint': endpoint,
                          'request_fields': sorted(request), 'api_key_configured': key_present,
                          'max_requests': 1, 'retries': 0, 'pagination': False,
                          'kind': args.kind},
                         indent=2, ensure_ascii=False))
        return 0
    try:
        result = run_probe(ROOT, kind=args.kind)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print('Could not write private probe evidence; no automatic retry.', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
