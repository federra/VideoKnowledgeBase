import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from '../src/api/client';
const rid = '11111111-1111-4111-8111-111111111111';
const wid = '22222222-2222-4222-8222-222222222222';
const fid = '33333333-3333-4333-8333-333333333333';
const session = { org_id: wid, member_id: fid, display_name: '测试成员', actions: [],
    authz_version: '9007199254740993', csrf_token: 'a'.repeat(64), expires_at: '2030-01-01T00:00:00.000000Z' };
const file = { id: fid, byte_size: '9007199254740993', original_name: '真实.txt', media_type: 'text/plain',
    sha256: 'b'.repeat(64), validation_state: 'accepted', created_at: '2026-10-17T00:00:00.000000Z' };
const envelope = (data: unknown, status = 200) => new Response(JSON.stringify({ request_id: rid, data }), { status, headers: { 'Content-Type': 'application/json', 'X-Request-ID': rid } });
const failure = (status: number, code: string) => new Response(JSON.stringify({ request_id: rid,
    error: { code, message: 'private stack REDFOX_API_KEY=do-not-show', field_paths: ['body.work_id'] } }), { status, headers: { 'Content-Type': 'application/json' } });
const metadata = { work_id: wid, expected_work_lock_version: '9007199254740993', original_name: '真实 &.txt', media_type: 'text/plain' as const };
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
describe('真实请求传输与安全边界', () => {
    it('按运行契约读取会话，保留空动作及大整数原字符串，不持久化令牌', async () => {
        const fetcher = vi.fn(async () => envelope(session));
        const storage = vi.spyOn(Storage.prototype, 'setItem');
        const client = new ApiClient({ fetcher });
        expect(await client.getSession()).toEqual(session);
        expect(fetcher.mock.calls[0]).toMatchObject(['/api/v1/session', { credentials: 'same-origin', cache: 'no-store', redirect: 'error' }]);
        expect(storage).not.toHaveBeenCalled();
    });
    it('写请求无CSRF即失败，取得会话后发原始字节与显式幂等键，版本不转数字', async () => {
        const fetcher = vi.fn().mockResolvedValueOnce(envelope(session)).mockResolvedValueOnce(envelope(file, 201));
        const client = new ApiClient({ fetcher });
        await expect(client.uploadFile(new Blob(['body']), metadata, rid)).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
        expect(fetcher).not.toHaveBeenCalled();
        await client.getSession();
        const body = new Blob(['body']);
        expect(await client.uploadFile(body, metadata, rid)).toEqual(file);
        const [url, init] = fetcher.mock.calls[1];
        expect(new URL(url, 'http://localhost').searchParams.get('expected_work_lock_version')).toBe('9007199254740993');
        expect(new URL(url, 'http://localhost').searchParams.get('original_name')).toBe('真实 &.txt');
        expect(init.body).toBe(body);
        expect(new Headers(init.headers).get('X-CSRF-Token')).toBe(session.csrf_token);
        expect(new Headers(init.headers).get('Idempotency-Key')).toBe(rid);
        expect(new Headers(init.headers).get('Content-Type')).toBe('application/octet-stream');
    });
    it('文件GET支持父对象、返回二进制；JSON拒绝不是可下载文件', async () => {
        const fetcher = vi.fn().mockResolvedValueOnce(new Response('bytes', { headers: { 'Content-Type': 'application/octet-stream' } }))
            .mockResolvedValueOnce(failure(404, 'NOT_FOUND'));
        const client = new ApiClient({ fetcher });
        const blob = await client.downloadFile(fid, { parent_kind: 'works', parent_id: wid });
        expect(await blob.text()).toBe('bytes');
        expect(fetcher.mock.calls[0][0]).toContain(`parent_id=${wid}`);
        await expect(client.downloadFile(fid)).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' });
    });
    it.each([[401, 'AUTH_REQUIRED'], [403, 'ACCESS_DENIED'], [404, 'NOT_FOUND'], [409, 'VERSION_CONFLICT'],
        [422, 'VALIDATION_FAILED'], [429, 'RATE_LIMITED'], [503, 'SERVICE_NOT_READY'], [500, 'INTERNAL_ERROR']])('%s保留安全错误类别和request_id，不透传服务端正文或自动重试', async (status, code) => {
        const fetcher = vi.fn(async () => failure(status as number, code as string));
        const client = new ApiClient({ fetcher });
        const error = await client.getSession().catch(e => e);
        expect(error).toBeInstanceOf(ApiError);
        expect(error).toMatchObject({ status, code, requestId: rid, fieldPaths: ['body.work_id'] });
        expect(error.message).not.toContain('private');
        expect(error.message).not.toContain('REDFOX');
        expect(fetcher).toHaveBeenCalledOnce();
    });
    it('HTML错误与损坏成功JSON明确失败，不读取Demo兜底', async () => {
        const fetcher = vi.fn().mockResolvedValueOnce(new Response('<html>private stack</html>', { status: 502 }))
            .mockResolvedValueOnce(new Response('{bad', { headers: { 'Content-Type': 'application/json' } }))
            .mockResolvedValueOnce(envelope({ unexpected: 'shape' }));
        const client = new ApiClient({ fetcher });
        await expect(client.getSession()).rejects.toMatchObject({ status: 502, code: 'HTTP_ERROR' });
        await expect(client.getSession()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
        await expect(client.getSession()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    });
    it('仅允许同源API路径，拒绝跨域、协议相对路径、路径逃逸和重定向', async () => {
        const fetcher = vi.fn();
        const client = new ApiClient({ fetcher });
        for (const url of ['https://evil.test/api/v1/session', '//evil.test/api', '/api/../private', '/api/%2e%2e/private', '/api\\evil', '/api/v1/x#fragment']) {
            await expect(client.get(url, value => value)).rejects.toMatchObject({ code: 'INVALID_REQUEST' });
        }
        expect(fetcher).not.toHaveBeenCalled();
    });
    it('写请求网络中断不自动重发，错误标明结果须核验', async () => {
        const fetcher = vi.fn().mockResolvedValueOnce(envelope(session)).mockRejectedValueOnce(new TypeError('secret URL'));
        const client = new ApiClient({ fetcher });
        await client.getSession();
        const e = await client.uploadFile(new Blob(['x']), metadata, rid).catch(e => e);
        expect(e.code).toBe('NETWORK_ERROR');
        expect(e.message).toContain('核验');
        expect(fetcher).toHaveBeenCalledTimes(2);
    });
    it('支持AbortSignal和超时，取消／超时不会变成空成功', async () => {
        vi.useFakeTimers();
        const fetcher = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
        }));
        const client = new ApiClient({ fetcher, timeoutMs: 100 });
        const controller = new AbortController();
        const cancelled = client.getSession(controller.signal).catch(e => e);
        controller.abort();
        expect(await cancelled).toMatchObject({ code: 'REQUEST_CANCELLED' });
        const timed = client.getSession().catch(e => e);
        await vi.advanceTimersByTimeAsync(101);
        expect(await timed).toMatchObject({ code: 'TIMEOUT' });
    });
    it('登录切换与401清除API缓存，旧响应不能恢复旧会话或内容', async () => {
        let resolveOld!: (response: Response) => void;
        const purge = vi.fn();
        const fetcher = vi.fn().mockResolvedValueOnce(envelope(session))
            .mockImplementationOnce(() => new Promise<Response>(resolve => { resolveOld = resolve; }))
            .mockResolvedValueOnce(failure(401, 'AUTH_REQUIRED'));
        const client = new ApiClient({ fetcher, onBoundary: purge });
        await client.getSession();
        const pending = client.getSession().catch(e => e);
        await expect(client.getSession()).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
        resolveOld(envelope(session));
        expect(await pending).toMatchObject({ code: 'REQUEST_CANCELLED' });
        await expect(client.uploadFile(new Blob(), metadata, rid)).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
        expect(purge).toHaveBeenCalled();
    });
    it('登录和退出均不缓存密码，退出后不能继续沿用原CSRF', async () => {
        const fetcher = vi.fn().mockResolvedValueOnce(envelope(session)).mockResolvedValueOnce(envelope({ acknowledged: true }));
        const client = new ApiClient({ fetcher });
        await client.login({ org_id: wid, login_name: 'test', password: 'test password' });
        expect(await client.logout()).toEqual({ acknowledged: true });
        await expect(client.uploadFile(new Blob(), metadata, rid)).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
        expect(fetcher).toHaveBeenCalledTimes(2);
    });
});
it('旧会话的迟到错误正文不能注销新会话', async () => {
    let finishBody!: (body: unknown) => void;
    const stale = failure(401, 'AUTH_REQUIRED');
    vi.spyOn(stale, 'json').mockImplementation(() => new Promise(resolve => { finishBody = resolve; }));
    const fetcher = vi.fn().mockResolvedValueOnce(envelope(session)).mockResolvedValueOnce(stale)
        .mockResolvedValueOnce(envelope({ ...session, member_id: rid })).mockResolvedValueOnce(envelope(file, 201));
    const client = new ApiClient({ fetcher });
    await client.getSession();
    const old = client.getSession().catch(e => e);
    await vi.waitFor(() => expect(finishBody).toBeTypeOf('function'));
    await client.login({ org_id: wid, login_name: 'new member', password: 'test password' });
    finishBody({ request_id: rid, error: { code: 'AUTH_REQUIRED' } });
    expect(await old).toMatchObject({ code: 'REQUEST_CANCELLED' });
    await expect(client.uploadFile(new Blob(), metadata, rid)).resolves.toMatchObject({ id: fid });
});
it('身份变更期间不并发发起第二个登录或旧Cookie会话恢复', async () => {
    let finishLogin!: (response: Response) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { finishLogin = resolve; }));
    const client = new ApiClient({ fetcher });
    const login = client.login({ org_id: wid, login_name: 'one', password: 'test password' });
    await expect(client.login({ org_id: wid, login_name: 'two', password: 'other password' })).rejects.toMatchObject({ code: 'AUTH_CHANGE_IN_PROGRESS' });
    await expect(client.getSession()).rejects.toMatchObject({ code: 'AUTH_CHANGE_IN_PROGRESS' });
    expect(fetcher).toHaveBeenCalledOnce();
    finishLogin(envelope(session));
    await login;
});

it('写入成功响应损坏时提示核验原请求，不鼓励新建请求',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(envelope(session)).mockResolvedValueOnce(envelope({unexpected:true},201));
  const client=new ApiClient({fetcher});
  await client.getSession();
  const error=await client.uploadFile(new Blob(),metadata,rid).catch(e=>e);
  expect(error.code).toBe('INVALID_RESPONSE');
  expect(error.message).toContain('核验');
});

it('登录网络失败能给查询边界提供明确错误，而非永久加载',async()=>{
  const client=new ApiClient({fetcher:vi.fn().mockRejectedValue(new TypeError('offline'))});
  await expect(client.login({org_id:wid,login_name:'test',password:'test password'})).rejects.toMatchObject({code:'NETWORK_ERROR'});
  expect(client.accessError).toMatchObject({code:'NETWORK_ERROR'});
});

it.each([[403,'ACCESS_DENIED'],[404,'NOT_FOUND']])('收到%s后仍能直接撤销有效会话',async(status,code)=>{
  const fetcher=vi.fn().mockResolvedValueOnce(envelope(session)).mockResolvedValueOnce(failure(status as number,code as string))
    .mockResolvedValueOnce(envelope({acknowledged:true}));
  const client=new ApiClient({fetcher});
  await client.getSession();
  await expect(client.downloadFile(fid)).rejects.toMatchObject({status});
  expect(await client.logout()).toEqual({acknowledged:true});
  expect(fetcher.mock.calls[2][1].method).toBe('DELETE');
  expect(new Headers(fetcher.mock.calls[2][1].headers).get('X-CSRF-Token')).toBe(session.csrf_token);
  await expect(client.uploadFile(new Blob(),metadata,rid)).rejects.toMatchObject({code:'AUTH_REQUIRED'});
});
