'use client'

import { useQuery } from '@tanstack/react-query'

import { get } from '@/lib/api'

/**
 * The workspace clock (may be pinned in the demo). The events endpoint returns `now` alongside its items;
 * asking for a window far in the future keeps the response empty and cheap.
 */
export function useWorkspaceNow(): string | undefined {
  const q = useQuery({
    queryKey: ['workspace-now'],
    queryFn: () => get<{ now: string }>('/api/events?start=2999-01-01T00:00:00Z'),
    staleTime: 5 * 60_000,
  })
  return q.data?.now
}
