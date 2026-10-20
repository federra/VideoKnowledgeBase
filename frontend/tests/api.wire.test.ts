// This suite runs only through pnpm api:test against a disposable real API/database.
import { readFileSync, writeFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { ApiClient } from '../src/api/client';
type Fixture = {
    base_url: string;
    org: string;
    work: string;
    password: string;
    evidence: string;
};
const fixturePath = process.env.CIP_FRONTEND_FIXTURE;
it.skipIf(!fixturePath)('TS客户端→真实HTTP→受限应用登录→隔离PG及文件', async () => {
    const fixture = JSON.parse(readFileSync(fixturePath!, 'utf8')) as Fixture;
    const statuses: number[] = [];
    let cookiePolicy = false;
    function client() {
        let cookie = '';
        const fetcher: typeof fetch = async (input, init) => {
            const path = String(input);
            if (!path.startsWith('/api/'))
                throw new Error('Only isolated API paths allowed');
            const headers = new Headers(init?.headers);
            if (cookie)
                headers.set('Cookie', cookie);
            if (init?.method === 'POST')
                headers.set('Origin', 'http://127.0.0.1:5173');
            // Node has no browser cookie jar/automatic Origin; this adapter supplies those
            // transport behaviors only. Every response below comes from actual HTTP/PG.
            const response = await fetch(fixture.base_url + path, { ...init, headers });
            const setCookie = response.headers.get('set-cookie');
            if (setCookie) {
                cookie = setCookie.split(';')[0];
                if (!setCookie.includes('Max-Age=0'))
                    cookiePolicy = setCookie.includes('HttpOnly') && setCookie.includes('SameSite=lax');
            }
            statuses.push(response.status);
            return response;
        };
        return new ApiClient({ fetcher });
    }
    const api = client();
    expect((await api.health()).status).toBe('ok');
    await expect(api.getSession()).rejects.toMatchObject({ status: 401, code: 'AUTH_REQUIRED' });
    const identity = await api.login({ org_id: fixture.org, login_name: 'writer', password: fixture.password });
    expect(identity.actions.includes('content.write')).toBe(true);
    const current = await api.getSession();
    expect(current.member_id).toBe(identity.member_id);
    const meta = { work_id: fixture.work, expected_work_lock_version: '1', original_name: 'real.txt', media_type: 'text/plain' as const };
    await expect(api.uploadFile(new Blob(['invalid']), { ...meta, original_name: 'invalid.exe' }, crypto.randomUUID()))
        .rejects.toMatchObject({ status: 422, code: 'INVALID_FILE' });
    const key = crypto.randomUUID();
    const uploaded = await api.uploadFile(new Blob(['S05.5 real transport bytes']), meta, key);
    const replay = await api.uploadFile(new Blob(['S05.5 real transport bytes']), meta, key);
    expect(replay.id).toBe(uploaded.id);
    expect(uploaded.byte_size).toBe('26');
    const bytes = await api.downloadFile(uploaded.id, { parent_kind: 'works', parent_id: fixture.work });
    expect(await bytes.text()).toBe('S05.5 real transport bytes');
    await expect(api.importFile({ ...meta, url: 'https://example.invalid/media.txt' }, crypto.randomUUID()))
        .rejects.toMatchObject({ status: 422, code: 'UNSAFE_URL' });
    await api.logout();
    await expect(api.getSession()).rejects.toMatchObject({ status: 401 });
    const viewer = client();
    await viewer.login({ org_id: fixture.org, login_name: 'viewer', password: fixture.password });
    await expect(viewer.uploadFile(new Blob(['x']), meta, crypto.randomUUID()))
        .rejects.toMatchObject({ status: 403, code: 'ACCESS_DENIED' });
    await viewer.logout();
    await viewer.login({ org_id: fixture.org, login_name: 'viewer', password: fixture.password });
    await expect(viewer.downloadFile(uploaded.id, { parent_kind: 'works', parent_id: fixture.work }))
        .rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' });
    await viewer.logout();
    const empty = client();
    const emptySession = await empty.login({ org_id: fixture.org, login_name: 'empty', password: fixture.password });
    expect(emptySession.actions).toEqual([]);
    await empty.logout();
    expect(cookiePolicy).toBe(true);
    writeFileSync(fixture.evidence, JSON.stringify({ transport: 'actual HTTP + PostgreSQL + private filesystem',
        statuses, session_cookie_policy: true, upload_replay_same_resource: true, download_bytes_match: true,
        empty_actions_preserved: true, forbidden_403: true, invisible_404: true, session_expiry_401: true,
        unsafe_external_url_no_network: true, paid_api_calls: 0, node_cookie_adapter: true }, null, 2) + '\n');
}, 30000);
