"""A TOP claim depends on the entire directory, including empty end pages."""

import json

from app.connectors.douyin_series import top
from app.connectors.redfox import AdapterError
from app.security.errors import Denied


def require_directory(c, p, job, az):
    rows = c.exec_driver_sql('SELECT r.* FROM raw_assets r JOIN collection_calls cc ON cc.org_id=r.org_id AND cc.id=r.collection_call_id WHERE r.org_id=%s AND r.collection_job_id=%s ORDER BY cc.sequence_no', (p.org_id, job['id'])).mappings().all()
    cursor, pages = 0, []
    for raw in rows:
        try:
            body = json.loads(raw['body_text'])
        except ValueError:
            continue
        if isinstance(body, dict) and 'series_infos' in body:
            az.read('raw_assets', raw['id'])
            pages.append((cursor, body))
            cursor = body['cursor']
    try:
        return top(pages, job['safe_request']['sec_user_id'], job['safe_request']['uid'])
    except (AdapterError, KeyError, TypeError):
        raise Denied('SOURCE_UNAVAILABLE') from None
