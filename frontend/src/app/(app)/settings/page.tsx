'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clock, Plus, RefreshCw, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useModelsHealth } from '@/components/system/connectors'
import { ModelHealthSummary, ModelSelect } from '@/components/system/models'
import { JobProgress, SwitchRow } from '@/components/system/shared'
import { useJob } from '@/components/system/use-job'
import { useToast } from '@/components/toast'
import { Button, Card, CardHeader, ErrorState, Input, Label, LoadingRows, PageHeader, Select } from '@/components/ui/primitives'
import { errorMessage, get, post, put } from '@/lib/api'
import type { JobStart, NotificationCategory, Settings } from '@/lib/types-system'
import { fmtDateTime } from '@/lib/utils'

const BRIEFING_SECTIONS: { key: string; label: string; hint: string }[] = [
  { key: 'today', label: 'Today at a glance', hint: 'Counts of meetings, deadlines, overdue items' },
  { key: 'meetings', label: 'Meetings', hint: 'Today and tomorrow' },
  { key: 'deadlines', label: 'Deadlines', hint: 'Due in the next 3 days' },
  { key: 'tasks', label: 'Tasks', hint: 'Open and blocked tasks' },
  { key: 'overdue', label: 'Overdue commitments', hint: 'Promises past due' },
  { key: 'awaiting', label: 'Awaiting your reply', hint: 'People waiting on you' },
  { key: 'followups', label: 'Follow-ups', hint: 'Requests that look stalled' },
  { key: 'projects', label: 'Projects', hint: 'Health with explained signals' },
  { key: 'changes', label: 'Recent changes', hint: 'What changed since yesterday' },
]

export default function SettingsPage() {
  const q = useQuery({ queryKey: ['settings'], queryFn: () => get<Settings>('/api/settings') })
  if (q.isLoading) return <LoadingRows rows={10} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const s = q.data
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="System" title="Settings" description="Models, time, how Threadline should behave, what it notifies you about, and maintenance." />
      {s.clock_override && (
        <div className="flex items-start gap-2 rounded-md border border-uncertain/30 bg-uncertain-wash px-3 py-2 text-sm text-ink-2" role="note">
          <Clock className="mt-0.5 h-4 w-4 shrink-0 text-uncertain" />
          <span>
            Demo clock pinned to <span className="font-medium text-ink">{fmtDateTime(s.clock_override)} UTC</span>. “Today”, overdue and upcoming are computed against this time so the synthetic data stays meaningful.
          </span>
        </div>
      )}
      <ModelsCard key={`${s.reasoning_model}|${s.extraction_model}|${s.llm_extraction_enabled}`} settings={s} />
      <div className="grid gap-5 lg:grid-cols-2">
        <TimezoneCard key={s.timezone} settings={s} />
        <ProceduralCard key={JSON.stringify(s.procedural_prefs)} settings={s} />
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <NotificationsCard />
        <BriefingCard />
      </div>
      <MaintenanceCard />
    </div>
  )
}

function useSaveSettings() {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: (body: Partial<Pick<Settings, 'reasoning_model' | 'extraction_model' | 'llm_extraction_enabled' | 'timezone' | 'procedural_prefs'>>) => put<Settings>('/api/settings', body),
    onSuccess: (d) => {
      qc.setQueryData(['settings'], d)
      toast('Settings saved.')
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
}

function ModelsCard({ settings }: { settings: Settings }) {
  const health = useModelsHealth()
  const save = useSaveSettings()
  const [reasoning, setReasoning] = useState(settings.reasoning_model)
  const [extraction, setExtraction] = useState(settings.extraction_model)
  const [llmEx, setLlmEx] = useState(settings.llm_extraction_enabled)
  const dirty = reasoning !== settings.reasoning_model || extraction !== settings.extraction_model || llmEx !== settings.llm_extraction_enabled
  const models = health.data?.local.models ?? []
  return (
    <Card>
      <CardHeader
        title="Models"
        description="Choose from models your local runtime reports. Embeddings are fixed by the server and always local."
        action={
          <Button size="sm" variant="ghost" onClick={() => health.refetch()} loading={health.isFetching} aria-label="Re-check model health">
            <RefreshCw className="h-3.5 w-3.5" /> Re-check
          </Button>
        }
      />
      <div className="space-y-4 p-4">
        {health.isLoading ? <LoadingRows rows={2} /> : health.error || !health.data ? <ErrorState error={health.error} retry={() => health.refetch()} /> : <ModelHealthSummary health={health.data} />}
        <div className="grid gap-4 sm:grid-cols-2">
          <ModelSelect id="reasoning-model" label="Reasoning model" hint="(assistant answers, briefs)" value={reasoning} models={models} onChange={setReasoning} />
          <ModelSelect id="extraction-model" label="Extraction model" hint="(used when LLM extraction is on)" value={extraction} models={models} onChange={setExtraction} />
        </div>
        <div className="rounded-md border border-line p-3">
          <SwitchRow
            label="Use the LLM for extraction"
            description="Adds model-based extraction of commitments, decisions and entities on top of the deterministic rules. Noticeably slower on CPU-only machines: expect minutes for a large import."
            checked={llmEx}
            onChange={setLlmEx}
          />
        </div>
        <div className="flex justify-end gap-2">
          {dirty && (
            <Button
              variant="ghost"
              onClick={() => {
                setReasoning(settings.reasoning_model)
                setExtraction(settings.extraction_model)
                setLlmEx(settings.llm_extraction_enabled)
              }}
            >
              Reset
            </Button>
          )}
          <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate({ reasoning_model: reasoning, extraction_model: extraction, llm_extraction_enabled: llmEx })}>
            Save models
          </Button>
        </div>
      </div>
    </Card>
  )
}

function timezones(current: string): string[] {
  let list: string[] = []
  try {
    list = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.('timeZone') ?? []
  } catch {
    list = []
  }
  if (!list.includes('UTC')) list = ['UTC', ...list]
  if (current && !list.includes(current)) list = [current, ...list]
  return list
}

function TimezoneCard({ settings }: { settings: Settings }) {
  const save = useSaveSettings()
  const [tz, setTz] = useState(settings.timezone)
  const zones = useMemo(() => timezones(settings.timezone), [settings.timezone])
  const browserTz = typeof Intl !== 'undefined' ? Intl.DateTimeFormat().resolvedOptions().timeZone : null
  return (
    <Card>
      <CardHeader title="Time zone" description="Used to interpret “tomorrow”, “end of week” and meeting times." />
      <div className="space-y-3 p-4">
        <div>
          <Label htmlFor="tz">Time zone</Label>
          <Select id="tz" className="w-full" value={tz} onChange={(e) => setTz(e.target.value)}>
            {zones.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          {browserTz && browserTz !== tz ? (
            <button type="button" className="text-xs text-accent hover:underline" onClick={() => setTz(browserTz)}>
              Use this browser’s zone ({browserTz})
            </button>
          ) : (
            <span />
          )}
          <Button variant="primary" disabled={tz === settings.timezone} loading={save.isPending} onClick={() => save.mutate({ timezone: tz })}>
            Save time zone
          </Button>
        </div>
      </div>
    </Card>
  )
}

function ProceduralCard({ settings }: { settings: Settings }) {
  const save = useSaveSettings()
  const [items, setItems] = useState<string[]>(settings.procedural_prefs)
  const [draft, setDraft] = useState('')
  const dirty = JSON.stringify(items) !== JSON.stringify(settings.procedural_prefs)
  const add = () => {
    const v = draft.trim()
    if (v && !items.includes(v)) setItems([...items, v])
    setDraft('')
  }
  return (
    <Card>
      <CardHeader title="How Threadline should work" description="Procedural memory: standing instructions the assistant follows in every answer." />
      <div className="space-y-3 p-4">
        {items.length === 0 ? (
          <p className="text-sm text-ink-3">No preferences yet. Example: “Always show evidence when summarizing project decisions.”</p>
        ) : (
          <ul className="space-y-1.5">
            {items.map((it, idx) => (
              <li key={`${it}-${idx}`} className="flex items-start gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-ink">
                <span className="flex-1">{it}</span>
                <button type="button" className="rounded p-0.5 text-ink-3 hover:bg-sunken hover:text-ink" aria-label={`Remove preference: ${it}`} onClick={() => setItems(items.filter((_, i) => i !== idx))}>
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            add()
          }}
        >
          <label htmlFor="pref-new" className="sr-only">
            New preference
          </label>
          <Input id="pref-new" value={draft} maxLength={500} onChange={(e) => setDraft(e.target.value)} placeholder="Always show evidence when summarizing project decisions" />
          <Button type="submit" disabled={!draft.trim()} aria-label="Add preference">
            <Plus className="h-4 w-4" />
          </Button>
        </form>
        <div className="flex justify-end">
          <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate({ procedural_prefs: items })}>
            Save preferences
          </Button>
        </div>
      </div>
    </Card>
  )
}

function NotificationsCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const ref = useRef<HTMLDivElement>(null)
  const q = useQuery({ queryKey: ['notifications'], queryFn: () => get<{ categories: NotificationCategory[] }>('/api/notifications') })
  const [pending, setPending] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: (prefs: Record<string, boolean>) => put<{ categories: NotificationCategory[] }>('/api/notifications/preferences', { prefs }),
    onMutate: (prefs) => {
      setPending(Object.keys(prefs)[0])
      const prev = qc.getQueryData<{ categories: NotificationCategory[] }>(['notifications'])
      if (prev) qc.setQueryData(['notifications'], { ...prev, categories: prev.categories.map((c) => (c.key in prefs ? { ...c, enabled: prefs[c.key] } : c)) })
      return { prev }
    },
    onSettled: () => setPending(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['notifications'] })
      toast('Notification preferences saved.')
    },
    onError: (e, _p, c) => {
      if (c?.prev) qc.setQueryData(['notifications'], c.prev)
      toast(errorMessage(e), 'error')
    },
  })
  const loaded = !!q.data
  useEffect(() => {
    if (loaded && typeof window !== 'undefined' && window.location.hash === '#notifications') ref.current?.scrollIntoView({ block: 'start' })
  }, [loaded])
  return (
    <div id="notifications" ref={ref} className="scroll-mt-20">
      <Card className="h-full">
        <CardHeader title="Notifications" description="Which proactive alerts Threadline may raise. Turning one off stops new alerts of that kind." />
        {q.isLoading ? (
          <LoadingRows rows={4} />
        ) : q.error || !q.data ? (
          <ErrorState error={q.error} retry={() => q.refetch()} />
        ) : (
          <div className="divide-y divide-line">
            {q.data.categories.map((c) => (
              <div key={c.key} className="px-4 py-2.5">
                <SwitchRow label={c.label} checked={c.enabled} disabled={pending === c.key} onChange={(v) => save.mutate({ [c.key]: v })} />
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

function BriefingCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['briefing'], queryFn: () => get<{ sections: Record<string, unknown> }>('/api/briefing') })
  const current = useMemo(() => (q.data ? BRIEFING_SECTIONS.map((s) => s.key).filter((k) => k in q.data.sections) : []), [q.data])
  const [sel, setSel] = useState<string[] | null>(null)
  const selected = sel ?? current
  const dirty = sel !== null && JSON.stringify([...sel].sort()) !== JSON.stringify([...current].sort())
  const save = useMutation({
    mutationFn: (sections: string[]) => put<{ ok: boolean; sections: string[] }>('/api/briefing/config', { sections }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['briefing'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setSel(null)
      toast('Briefing sections saved.')
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  return (
    <Card className="h-full">
      <CardHeader title="Daily briefing" description="Sections shown in your briefing and on the dashboard." />
      {q.isLoading ? (
        <LoadingRows rows={4} />
      ) : q.error || !q.data ? (
        <ErrorState error={q.error} retry={() => q.refetch()} />
      ) : (
        <div className="p-4">
          <fieldset>
            <legend className="sr-only">Briefing sections</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {BRIEFING_SECTIONS.map((s) => (
                <label key={s.key} className="flex items-start gap-2 rounded-md px-1 py-1 text-sm hover:bg-sunken">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
                    checked={selected.includes(s.key)}
                    onChange={(e) => setSel(e.target.checked ? [...selected, s.key] : selected.filter((k) => k !== s.key))}
                  />
                  <span>
                    <span className="text-ink">{s.label}</span>
                    <span className="block text-[11px] text-ink-3">{s.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="mt-3 flex items-center justify-end gap-2">
            {selected.length === 0 && <span className="text-xs text-warning">Pick at least one section.</span>}
            <Button variant="primary" disabled={!dirty || selected.length === 0} loading={save.isPending} onClick={() => save.mutate(BRIEFING_SECTIONS.map((s) => s.key).filter((k) => selected.includes(k)))}>
              Save sections
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

function MaintenanceCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const [rebuildJob, setRebuildJob] = useState<string | null>(null)
  const [proactiveJob, setProactiveJob] = useState<string | null>(null)
  const rebuildState = useJob(rebuildJob)
  const proactiveState = useJob(proactiveJob)
  const rebuild = useMutation({ mutationFn: () => post<JobStart>('/api/memory/rebuild'), onSuccess: (r) => setRebuildJob(r.job_id), onError: (e) => toast(errorMessage(e), 'error') })
  const proactive = useMutation({ mutationFn: () => post<JobStart>('/api/intelligence/run'), onSuccess: (r) => setProactiveJob(r.job_id), onError: (e) => toast(errorMessage(e), 'error') })
  return (
    <Card>
      <CardHeader title="Maintenance" description="Both run in the background; you can keep working." />
      <div className="grid gap-4 p-4 md:grid-cols-2">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-ink">Rebuild memory</p>
              <p className="text-xs text-ink-3">Reprocesses every stored source item: extraction, entity resolution, evidence and timeline.</p>
            </div>
            <Button loading={rebuild.isPending} disabled={rebuildState.isActive} onClick={() => rebuild.mutate()}>
              <RefreshCw className="h-4 w-4" /> Rebuild memory
            </Button>
          </div>
          <JobProgress
            jobId={rebuildJob}
            label="Rebuilding memory"
            onDone={(j) => {
              qc.invalidateQueries()
              toast(j.status === 'succeeded' ? 'Memory rebuild queued all items; processing continues in the event queue.' : `Rebuild failed: ${j.error ?? ''}`, j.status === 'succeeded' ? 'success' : 'error')
            }}
          />
        </div>
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-ink">Run proactive analysis now</p>
              <p className="text-xs text-ink-3">Re-checks commitments for fulfilment and refreshes follow-ups, risks and notifications.</p>
            </div>
            <Button loading={proactive.isPending} disabled={proactiveState.isActive} onClick={() => proactive.mutate()}>
              <Sparkles className="h-4 w-4" /> Run now
            </Button>
          </div>
          <JobProgress
            jobId={proactiveJob}
            label="Proactive analysis"
            onDone={(j) => {
              qc.invalidateQueries()
              toast(j.status === 'succeeded' ? 'Proactive analysis finished.' : `Analysis failed: ${j.error ?? ''}`, j.status === 'succeeded' ? 'success' : 'error')
            }}
          />
        </div>
      </div>
    </Card>
  )
}
