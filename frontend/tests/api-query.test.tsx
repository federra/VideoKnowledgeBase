import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiProvider, useApi, useApiQuery } from '../src/api/provider';
import { ApiClient } from '../src/api/client';
const rid = '11111111-1111-4111-8111-111111111111';
const response = (data: unknown) => new Response(JSON.stringify({ request_id: rid, data }), { headers: { 'Content-Type': 'application/json' } });
const decode = (value: unknown) => { if (!Array.isArray(value) || !value.every(v => typeof v === 'string'))
    throw new Error('shape'); return value as string[]; };
function Probe({ filter = 'one' }: {
    filter?: string;
}) {
    const api = useApi();
    const state = useApiQuery(['test', filter], signal => api.get(`/api/v1/test?q=${filter}`, decode, signal), items => items.length === 0);
    return <><output aria-label="状态">{state.status}</output><div role="status">{state.message}</div>
    <div>{state.data?.join(',')}</div></>;
}
function setup(fetcher: typeof fetch) {
    const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const client = new ApiClient({ fetcher });
    return { queries, client, wrapper: ({ children }: {
            children: React.ReactNode;
        }) => <QueryClientProvider client={queries}><ApiProvider client={client}>{children}</ApiProvider></QueryClientProvider> };
}
describe('请求反馈与缓存隔离', () => {
    it.each([['正常', ['real record'], 'success'], ['空数据', [], 'empty']] as const)('%s保留真实数据，不补演示样例', async (_name, items, status) => {
        const fetcher = vi.fn(async () => response(items));
        const { wrapper } = setup(fetcher);
        render(<Probe />, { wrapper });
        await waitFor(() => expect(screen.getByLabelText('状态').textContent).toBe(status));
        if (status === 'empty')
            expect(screen.getByText('暂无数据').textContent).toBe('暂无数据');
        else
            expect(screen.getByText('real record')).toBeTruthy();
        expect(fetcher).toHaveBeenCalledOnce();
    });
    it.each([[403, 'ACCESS_DENIED', 'forbidden'], [404, 'NOT_FOUND', 'not-found'], [503, 'SERVICE_NOT_READY', 'error'], [401, 'AUTH_REQUIRED', 'unauthenticated']])('%s明确反馈并清除旧数据，不自动重试或显示Demo', async (status, code, expected) => {
        const fetcher = vi.fn(async () => new Response(JSON.stringify({ request_id: rid, error: { code, message: 'private' } }), { status: status as number, headers: { 'Content-Type': 'application/json' } }));
        const { wrapper, queries } = setup(fetcher);
        queries.setQueryData(['api', 'old scope', 'private'], ['old private record']);
        render(<Probe />, { wrapper });
        await waitFor(() => expect(screen.getByLabelText('状态').textContent).toBe(expected));
        expect(screen.queryByText('old private record')).toBeNull();
        expect(fetcher).toHaveBeenCalledOnce();
        if (status === 401 || status === 403 || status === 404)
            expect(queries.getQueryData(['api', 'old scope', 'private'])).toBeUndefined();
    });
    it('切换筛选立即清除旧结果，慢响应不能覆盖当前选择', async () => {
        let resolveOld!: (response: Response) => void;
        const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { resolveOld = resolve; }))
            .mockResolvedValueOnce(response(['new result']));
        const { wrapper } = setup(fetcher);
        const view = render(<Probe filter="one"/>, { wrapper });
        view.rerender(<Probe filter="two"/>);
        await screen.findByText('new result');
        await act(async () => { resolveOld(response(['stale record'])); });
        expect(screen.queryByText('stale record')).toBeNull();
        expect(screen.getByText('new result')).toBeTruthy();
    });
});

it('更换客户端实例时不会复用另一实例尚未完成的私有查询',async()=>{
  let oldResponse!:(response:Response)=>void;
  const first=new ApiClient({fetcher:vi.fn(()=>new Promise<Response>(resolve=>{oldResponse=resolve;}))});
  const second=new ApiClient({fetcher:vi.fn(async()=>response(['second client result']))});
  const queries=new QueryClient();
  function View({client}:{client:ApiClient}) {
    return <QueryClientProvider client={queries}><ApiProvider client={client}><Probe/></ApiProvider></QueryClientProvider>;
  }
  const view=render(<View client={first}/>);
  await waitFor(()=>expect(oldResponse).toBeTypeOf('function'));
  view.rerender(<View client={second}/>);
  await act(async()=>{oldResponse(response(['first client private record']));});
  await screen.findByText('second client result');
  expect(screen.queryByText('first client private record')).toBeNull();
});
