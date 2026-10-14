'use client'

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { get } from '@/lib/api'
import type { Job } from '@/lib/types-system'

export const TERMINAL = new Set(['succeeded', 'dead', 'failed'])

export function isJobFailed(status: string | undefined) {
  return status === 'dead' || status === 'failed'
}

/**
 * Poll GET /api/jobs/{id} until the job reaches a terminal state (succeeded / dead).
 * `onDone` fires once per job when it finishes (successfully or not).
 */
export function useJob(jobId: string | null | undefined, opts: { interval?: number; onDone?: (job: Job) => void } = {}) {
  const { interval = 1000, onDone } = opts
  const q = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => get<Job>(`/api/jobs/${jobId}`),
    enabled: !!jobId,
    staleTime: 0,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s && TERMINAL.has(s) ? false : interval
    },
  })
  const job = jobId ? q.data : undefined
  const fired = useRef<string | null>(null)
  const cb = useRef(onDone)
  useEffect(() => {
    cb.current = onDone
  }, [onDone])
  useEffect(() => {
    if (job && TERMINAL.has(job.status) && fired.current !== job.id) {
      fired.current = job.id
      cb.current?.(job)
    }
  }, [job])

  const status = job?.status
  return {
    job,
    error: q.error,
    isActive: !!jobId && (!status || !TERMINAL.has(status)),
    isDone: status === 'succeeded',
    isFailed: isJobFailed(status),
    percent: job?.progress?.percent ?? (status === 'succeeded' ? 100 : undefined),
    message: job?.progress?.message,
  }
}
