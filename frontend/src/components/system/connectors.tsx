'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { CalendarDays, Database, FolderOpen, Globe, HardDrive, Mail, Plug } from 'lucide-react'
import type { ReactNode } from 'react'

import { useToast } from '@/components/toast'
import { Badge, Button, ErrorState, LoadingRows } from '@/components/ui/primitives'
import { errorMessage, get, post } from '@/lib/api'
import type { CatalogItem, Integration, ModelsHealth } from '@/lib/types-system'
import { cn } from '@/lib/utils'

export const OAUTH_PENDING_KEY = 'threadline.oauth.pending'

export const CONNECTOR_ICON: Record<string, ReactNode> = {
  demo: <Database className="h-4 w-4" />,
  gmail: <Mail className="h-4 w-4" />,
  outlook: <Mail className="h-4 w-4" />,
  gcal: <CalendarDays className="h-4 w-4" />,
  mscal: <CalendarDays className="h-4 w-4" />,
  local_files: <FolderOpen className="h-4 w-4" />,
  notes: <HardDrive className="h-4 w-4" />,
  uploads: <HardDrive className="h-4 w-4" />,
}

export function connectorIcon(kind: string) {
  return CONNECTOR_ICON[kind] ?? <Plug className="h-4 w-4" />
}

export function useCatalog() {
  return useQuery({ queryKey: ['integrations', 'catalog'], queryFn: () => get<{ items: CatalogItem[] }>('/api/integrations/catalog'), staleTime: 60_000 })
}

export function useModelsHealth() {
  return useQuery({ queryKey: ['models-health'], queryFn: () => get<ModelsHealth>('/api/models/health'), staleTime: 30_000 })
}

/** Start Google OAuth: the backend creates a pending integration and returns the consent URL. */
export function useGoogleConnect() {
  const toast = useToast()
  return useMutation({
    mutationFn: (kind: string) => post<{ url: string; integration_id: string }>(`/api/integrations/google/${kind}/start`),
    onSuccess: (r) => {
      try {
        sessionStorage.setItem(OAUTH_PENDING_KEY, r.integration_id)
      } catch {
        /* storage unavailable: the callback page will explain */
      }
      window.location.assign(r.url)
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
}

/**
 * Connector catalog. Implemented connectors are actionable; planned ones are labelled and disabled.
 * `onLocalFolder` opens the folder dialog; `renderDemo` lets the caller decide how demo import works.
 */
export function ConnectorCatalog({ connected, onLocalFolder, renderDemo, compact }: { connected: Integration[]; onLocalFolder: () => void; renderDemo?: (c: CatalogItem) => ReactNode; compact?: boolean }) {
  const cat = useCatalog()
  const google = useGoogleConnect()
  if (cat.isLoading) return <LoadingRows rows={3} />
  if (cat.error || !cat.data) return <ErrorState error={cat.error} retry={() => cat.refetch()} />
  const items = [...cat.data.items].sort((a, b) => Number(b.implemented) - Number(a.implemented))
  const activeKinds = new Set(connected.filter((i) => i.status !== 'revoked').map((i) => i.kind))
  return (
    <ul className={cn('grid gap-3', compact ? 'sm:grid-cols-2' : 'sm:grid-cols-2 xl:grid-cols-3')}>
      {items.map((c) => {
        const isConnected = activeKinds.has(c.kind)
        let action: ReactNode = null
        let note: ReactNode = null
        if (!c.implemented) {
          action = (
            <Button size="sm" disabled aria-label={`${c.name} is planned`}>
              Planned
            </Button>
          )
        } else if (c.kind === 'local_files') {
          action = c.configured ? (
            <Button size="sm" variant="subtle" onClick={onLocalFolder}>
              Add folder
            </Button>
          ) : (
            <Button size="sm" disabled>
              Disabled
            </Button>
          )
          if (!c.configured) note = 'Disabled on this server. Set LOCAL_IMPORT_ROOTS to allow folder imports.'
        } else if (c.kind === 'gmail' || c.kind === 'gcal') {
          if (c.configured) {
            action = (
              <Button size="sm" variant="subtle" loading={google.isPending && google.variables === c.kind} onClick={() => google.mutate(c.kind)}>
                {isConnected ? 'Connect another' : 'Connect'}
              </Button>
            )
            note = 'Read-only scope. You will be sent to Google to grant access.'
          } else {
            action = (
              <Button size="sm" disabled>
                Not configured
              </Button>
            )
            note = (
              <>
                Needs Google OAuth credentials: set <code className="font-mono text-[11px]">GOOGLE_CLIENT_ID</code> and <code className="font-mono text-[11px]">GOOGLE_CLIENT_SECRET</code> in the backend environment and restart.
              </>
            )
          }
        } else if (c.kind === 'demo') {
          action = renderDemo ? renderDemo(c) : null
        }
        return (
          <li key={c.kind} className={cn('flex flex-col rounded-md border border-line bg-surface p-3', !c.implemented && 'bg-surface-2')}>
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-sunken', c.implemented ? 'text-ink-2' : 'text-ink-3')}>{connectorIcon(c.kind)}</span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-ink">{c.name}</div>
                  <div className="flex flex-wrap gap-1">
                    {!c.implemented && <Badge tone="neutral">Planned</Badge>}
                    {isConnected && <Badge tone="success">Connected</Badge>}
                    {c.requires_network ? (
                      <Badge tone="info" title="Fetches data over the network from the provider">
                        <Globe className="h-3 w-3" /> Network
                      </Badge>
                    ) : (
                      <Badge tone="neutral" title="Reads data on this machine only">
                        Offline
                      </Badge>
                    )}
                    {c.incremental && c.implemented && <Badge tone="neutral">Incremental</Badge>}
                  </div>
                </div>
              </div>
              <div className="shrink-0">{action}</div>
            </div>
            <p className="mt-2 text-xs text-ink-2">{c.description}</p>
            {note && <p className="mt-1.5 text-[11px] leading-4 text-ink-3">{note}</p>}
          </li>
        )
      })}
    </ul>
  )
}
