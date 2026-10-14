'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GitMerge, Search, ShieldQuestion, Users, X } from 'lucide-react'
import Link from 'next/link'
import { useDeferredValue, useState } from 'react'

import { useWorkspaceNow } from '@/components/memory/use-now'
import { useToast } from '@/components/toast'
import { Avatar, Confidence } from '@/components/ui/ai'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, LoadingRows, PageHeader } from '@/components/ui/primitives'
import { errorMessage, get, post } from '@/lib/api'
import type { MergeCandidate, MergeIdentity, PeopleResponse } from '@/lib/types-memory'
import { relDays } from '@/lib/utils'

export default function PeoplePage() {
  const [q, setQ] = useState('')
  const dq = useDeferredValue(q.trim())
  const now = useWorkspaceNow()
  const people = useQuery({
    queryKey: ['people', dq],
    queryFn: () => get<PeopleResponse>(`/api/people${dq ? `?q=${encodeURIComponent(dq)}` : ''}`),
    placeholderData: (prev) => prev,
  })
  const candidates = people.data?.merge_candidates ?? []

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="People"
        description="Everyone Threadline has met in your email, calendar, documents and notes, with what’s open between you."
      />

      {candidates.length > 0 && <DuplicateReview candidates={candidates} />}

      <Card>
        <CardHeader
          title="Directory"
          description={people.data ? `${people.data.items.length} ${people.data.items.length === 1 ? 'person' : 'people'}${dq ? ` matching “${dq}”` : ''}` : undefined}
          action={
            <div className="relative w-56 max-w-[50vw]">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name or email" aria-label="Search people" className="h-8 pl-8 text-xs" />
            </div>
          }
        />
        {people.isLoading ? (
          <LoadingRows rows={8} />
        ) : people.error ? (
          <ErrorState error={people.error} retry={() => people.refetch()} />
        ) : !people.data || people.data.items.length === 0 ? (
          <EmptyState
            icon={<Users className="h-4 w-4" />}
            title={dq ? 'Nobody matches that search' : 'No people yet'}
            description={dq ? 'Try part of a name or an email address.' : 'People appear here as soon as an email, meeting or document mentions them.'}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] font-medium uppercase tracking-wide text-ink-3">
                  <th scope="col" className="px-4 py-2 font-medium">Name</th>
                  <th scope="col" className="px-4 py-2 font-medium">Organization</th>
                  <th scope="col" className="px-4 py-2 font-medium">Last interaction</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Open items</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Emails sent</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {people.data.items.map((p) => (
                  <tr key={p.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5">
                      <Link href={`/people/${p.id}`} className="flex items-center gap-2.5 hover:text-accent">
                        <Avatar name={p.name} />
                        <span className="min-w-0">
                          <span className="block truncate font-medium text-ink">
                            {p.name}
                            {p.is_self && <span className="ml-1.5 text-xs font-normal text-ink-3">(you)</span>}
                          </span>
                          <span className="block truncate text-xs text-ink-3">{p.email ?? 'no email'}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="block truncate text-ink-2">{p.organization ?? '—'}</span>
                      {p.title && <span className="block truncate text-xs text-ink-3">{p.title}</span>}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-ink-2">{p.last_interaction_at ? relDays(p.last_interaction_at, now) : '—'}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {p.open_items > 0 ? <Badge tone="info">{p.open_items}</Badge> : <span className="text-ink-3">0</span>}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink-2">{p.emails_sent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function DuplicateReview({ candidates }: { candidates: MergeCandidate[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'merge' | 'reject' }) => post<{ ok: boolean; id?: string }>(`/api/people/merge-candidates/${id}`, { action }),
    onSuccess: (_r, v) => {
      toast(v.action === 'merge' ? 'Merged. All emails, meetings and commitments now point to one person.' : 'Kept as separate people. Threadline won’t suggest this pair again.')
      qc.invalidateQueries({ queryKey: ['people'] })
      qc.invalidateQueries({ queryKey: ['person'] })
      qc.invalidateQueries({ queryKey: ['graph'] })
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  return (
    <Card className="mb-5 border-uncertain/30">
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <ShieldQuestion className="h-4 w-4 text-uncertain" aria-hidden /> Possible duplicates
            <Badge tone="uncertain">{candidates.length}</Badge>
          </span>
        }
        description="These identities might be the same person, but the evidence isn’t conclusive. Uncertain identities are never merged automatically: you decide."
      />
      <ul className="divide-y divide-line">
        {candidates.map((c) => {
          const busy = decide.isPending && decide.variables?.id === c.id
          return (
            <li key={c.id} className="px-4 py-3">
              <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-start">
                <Identity who={c.a} />
                <span className="hidden self-center text-xs text-ink-3 sm:block" aria-hidden>
                  ↔
                </span>
                <Identity who={c.b} />
              </div>
              <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
                  <span className="text-ink-3">Match score</span>
                  <Confidence value={c.score} label="match score" />
                  {c.reasons.map((r) => (
                    <span key={r} className="text-ink-2">
                      · {r}
                    </span>
                  ))}
                </div>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="secondary" loading={busy && decide.variables?.action === 'reject'} disabled={busy} onClick={() => decide.mutate({ id: c.id, action: 'reject' })}>
                    <X className="h-3 w-3" /> Not the same person
                  </Button>
                  <Button size="sm" variant="primary" loading={busy && decide.variables?.action === 'merge'} disabled={busy} onClick={() => decide.mutate({ id: c.id, action: 'merge' })}>
                    <GitMerge className="h-3 w-3" /> Merge
                  </Button>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function Identity({ who }: { who: MergeIdentity | null }) {
  if (!who) return <div className="text-xs text-ink-3">(identity no longer exists)</div>
  return (
    <div className="min-w-0 rounded-md border border-line bg-surface-2 p-2.5">
      <Link href={`/people/${who.id}`} className="flex items-center gap-2 text-sm font-medium text-ink hover:text-accent">
        <Avatar name={who.name} className="h-5 w-5 text-[9px]" />
        <span className="truncate">{who.name}</span>
      </Link>
      <div className="mt-0.5 truncate text-xs text-ink-2">{who.email ?? 'no email'}</div>
      {who.aliases.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {who.aliases.map((a) => (
            <Badge key={a} tone="neutral">
              {a}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}
