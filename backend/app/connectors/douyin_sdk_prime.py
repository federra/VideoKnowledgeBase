"""Warm a resumed SDK page while blocking already acquired business API pages."""
import json
import time
from urllib.parse import parse_qsl, quote, urlsplit

from app.connectors.douyin_search import PATHS
from app.connectors.douyin_verification import CODE, retain_challenge

HOST = 'https://www.douyin.com'
COMMENTS = '/aweme/v1/web/comment/list/'
DETAIL = '/aweme/v1/web/aweme/detail/'


def prime(source, kind, target, *, private_root):
    if source.page is not None:
        source.page.close()
    page = source.page = source.ctx.new_page()
    source.page_key = (kind, target)
    source.native_headers = {}
    ready, restricted, detail_used = False, None, False

    def route(r):
        nonlocal ready, detail_used
        req = r.request
        u = urlsplit(req.url)
        p = dict(parse_qsl(u.query))
        if restricted or req.resource_type in ('media', 'image', 'font'):
            return r.abort()
        if u.hostname == 'www.douyin.com' and u.path.startswith('/aweme/'):
            initial = (
                kind == 'search' and u.path in PATHS and p.get('keyword') == '微电影'
                and p.get('search_channel') == 'aweme_video_web' and p.get('offset', '0') == '0'
            ) or (
                kind == 'comments' and u.path == COMMENTS and p.get('aweme_id') == target
                and p.get('cursor', '0') == '0'
            )
            if initial:
                source.fence()
                native = req.headers.get('uifid')
                source.native_headers = (
                    {'uifid': native} if isinstance(native, str) and 0 < len(native) <= 4096 else {}
                )
                if kind == 'search':
                    source.template, source.template_path = p, u.path
                ready = True
                return r.abort()
            if kind == 'comments' and u.path == DETAIL and p.get('aweme_id') == target and not detail_used:
                source.fence()
                detail_used = True
                return r.continue_()
            return r.abort()
        if req.is_navigation_request() and u.hostname not in ('www.douyin.com', 'douyin.com'):
            return r.abort()
        return r.continue_()

    def receive(response):
        nonlocal restricted
        u = urlsplit(response.url)
        if u.hostname == 'www.douyin.com' and u.path == DETAIL and response.status in (403, 429):
            restricted = response.status

    page.route('**/*', route)
    page.on('response', receive)
    try:
        source.fence()
        response = page.goto(
            HOST + '/search/' + quote('微电影') + '?type=video&sort_type=0'
            if kind == 'search' else HOST + '/video/' + target,
            wait_until='domcontentloaded', timeout=35000,
        )
        if response and response.status in (403, 429):
            return {'status': response.status, 'raw': '[SDK document restricted]', 'error': 'SOURCE_UNAVAILABLE'}
        if response and response.status == 200:
            try:
                challenge = retain_challenge(response.body(), private_root / 'verification')
            except Exception:  # noqa: BLE001 - native navigation may discard the response resource
                challenge = None
            if challenge:
                return {'status': 200, 'raw': json.dumps(challenge, ensure_ascii=False), 'error': CODE}
        end = time.monotonic() + 25
        while not ready and not restricted and time.monotonic() < end:
            source.fence()
            page.wait_for_timeout(250)
        return {
            'status': restricted or (200 if ready else None),
            'raw': '[SDK initialized; reused first business API blocked]' if ready else '[SDK initialization unavailable]',
            'error': 'SOURCE_UNAVAILABLE' if restricted or not ready else None,
        }
    finally:
        page.unroute('**/*', route)
        page.remove_listener('response', receive)
