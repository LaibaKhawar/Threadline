'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2 } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useRef } from 'react'

import { OAUTH_PENDING_KEY } from '@/components/system/connectors'
import { Card, ErrorState, PageHeader, Spinner } from '@/components/ui/primitives'
import { post } from '@/lib/api'
import type { Integration } from '@/lib/types-system'

function Callback() {
  const params = useSearchParams()
  const qc = useQueryClient()
  const code = params.get('code')
  const state = params.get('state')
  const oauthError = params.get('error')
  const started = useRef(false)
  const finish = useMutation({
    mutationFn: () => {
      let integrationId: string | null = null
      try {
        integrationId = sessionStorage.getItem(OAUTH_PENDING_KEY)
      } catch {
        integrationId = null
      }
      if (!integrationId) throw new Error('This browser tab has no pending connection. Start the connection again from Integrations.')
      return post<Integration>('/api/integrations/google/callback', { integration_id: integrationId, code, state })
    },
    onSuccess: () => {
      try {
        sessionStorage.removeItem(OAUTH_PENDING_KEY)
      } catch {
        /* ignore */
      }
      qc.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
  useEffect(() => {
    if (started.current || oauthError || !code || !state) return
    started.current = true
    finish.mutate()
  }, [code, state, oauthError, finish])

  return (
    <div className="mx-auto max-w-xl">
      <PageHeader eyebrow="Integrations" title="Connecting Google" />
      <Card className="p-4">
        {oauthError ? (
          <ErrorState error={new Error(`Google returned “${oauthError}”. Nothing was connected.`)} />
        ) : !code || !state ? (
          <ErrorState error={new Error('The callback is missing its code or state parameter.')} />
        ) : finish.isPending || finish.isIdle ? (
          <p className="flex items-center gap-2 text-sm text-ink-2">
            <Spinner /> Exchanging the authorisation code and storing the token (encrypted, on this machine)…
          </p>
        ) : finish.error ? (
          <ErrorState error={finish.error} />
        ) : (
          <p className="flex items-center gap-2 text-sm text-ink">
            <CheckCircle2 className="h-4 w-4 text-success" /> Connected {finish.data?.name}. Run a sync from Integrations to import it.
          </p>
        )}
        <div className="mt-4">
          <Link href="/integrations" className="inline-flex h-9 items-center rounded-md border border-line bg-surface px-3.5 text-sm font-medium text-ink hover:bg-sunken">
            Back to integrations
          </Link>
        </div>
      </Card>
    </div>
  )
}

export default function GoogleCallbackPage() {
  return (
    <Suspense>
      <Callback />
    </Suspense>
  )
}
