/**
 * TanStack Query hooks, one per RPC.
 *
 * Query keys live here rather than at call sites so that cache invalidation
 * after an approve can never miss a key (SPEC.md 8.3).
 */

'use client';

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { rewindClient } from './client';
import type { GetSystemHealthResponse } from '@/lib/gen/rewind/v1/api_pb';

export const queryKeys = {
  systemHealth: (deep: boolean) => ['systemHealth', { deep }] as const,
} as const;

/**
 * Poll system health.
 *
 * The shallow check is deliberately cheap on the worker side, so polling it
 * every few seconds is fine; only `rewind doctor` asks for the deep probe.
 */
export function useSystemHealth(options?: {
  deep?: boolean;
  refetchMs?: number;
}): UseQueryResult<GetSystemHealthResponse, Error> {
  const deep = options?.deep ?? false;

  return useQuery({
    queryKey: queryKeys.systemHealth(deep),
    queryFn: () => rewindClient.getSystemHealth({ deep }),
    refetchInterval: options?.refetchMs ?? 5_000,
    // A stopped Go API is an expected state while developing, not an
    // exceptional one: retry quietly and let the UI show it as down rather
    // than flooding the console.
    retry: 1,
    refetchOnWindowFocus: true,
  });
}
