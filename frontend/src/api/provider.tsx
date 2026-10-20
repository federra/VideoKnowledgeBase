/** Request state for real services. Demo rendering and storage never enter this boundary. */
import { createContext, useContext, useEffect, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiClient, ApiError } from './client';
const Context = createContext<ApiClient | null>(null);
export function ApiProvider({ children, client: supplied }: {
    children: ReactNode;
    client?: ApiClient;
}) {
    const queries = useQueryClient();
    const [owned] = useState(() => new ApiClient());
    const client = supplied ?? owned;
    useEffect(() => client.onBoundary(() => {
        void queries.cancelQueries({ queryKey: ['api'] });
        queries.removeQueries({ queryKey: ['api'] });
    }), [client, queries]);
    return <Context.Provider value={client}>{children}</Context.Provider>;
}
export function useApi() {
    const client = useContext(Context);
    if (!client)
        throw new Error('ApiProvider is required');
    return client;
}
export type ApiStatus = 'loading' | 'success' | 'empty' | 'error' | 'unauthenticated' | 'forbidden' | 'not-found' | 'cancelled';
export function feedback(error: unknown): {
    status: ApiStatus;
    message: string;
} {
    if (!(error instanceof ApiError))
        return { status: 'error', message: '请求未完成，请稍后重试' };
    const status: ApiStatus = error.status === 401 ? 'unauthenticated' : error.status === 403 ? 'forbidden' : error.status === 404 ? 'not-found' : error.code === 'REQUEST_CANCELLED' ? 'cancelled' : 'error';
    return { status, message: error.message };
}
export function useApiQuery<T>(key: readonly unknown[], load: (signal: AbortSignal) => Promise<T>, isEmpty: (data: T) => boolean) {
    const client = useApi();
    const scope = useSyncExternalStore(client.subscribe, client.snapshot, client.snapshot);
    const query = useQuery({
        queryKey: ['api', scope, ...key], queryFn: ({ signal }) => load(signal), enabled: !client.accessBlocked,
        retry: false, retryOnMount: false, staleTime: 0, gcTime: 0, refetchOnWindowFocus: true,
    });
    const error = client.accessError ?? query.error;
    const data = error || client.accessBlocked ? undefined : query.data;
    const state: {
        status: ApiStatus;
        message: string;
    } = error ? feedback(error)
        : data === undefined ? { status: 'loading', message: '正在加载' }
            : isEmpty(data) ? { status: 'empty', message: '暂无数据' } : { status: 'success', message: '' };
    return { ...state, data, error, requestId: error instanceof ApiError ? error.requestId : undefined,
        // Explicit retry is for reads only; writes use methods retaining caller-owned keys.
        refetch: query.refetch };
}
