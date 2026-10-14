'use client'

import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, Database, FolderOpen, RefreshCw } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { type ReactNode, useEffect, useState } from 'react'

import { TAGLINE, Wordmark } from '@/components/logo'
import { ConnectorCatalog, useModelsHealth } from '@/components/system/connectors'
import { ModelHealthSummary, ModelSelect } from '@/components/system/models'
import { JobProgress, LocalFolderDialog, ModeOptions, fmtNum, humanize } from '@/components/system/shared'
import { TERMINAL } from '@/components/system/use-job'
import { useToast } from '@/components/toast'
import { Badge, Button, ErrorState, LoadingRows, Spinner } from '@/components/ui/primitives'
import { ApiError, errorMessage, get, post, put } from '@/lib/api'
import type { AiMode, Integration, Inventory, Job, JobStart, JobsResponse, Privacy, Settings } from '@/lib/types-system'
import { cn } from '@/lib/utils'

type Me = { user: { id: string; email: string; display_name: string; is_demo: boolean; onboarding_completed: boolean; ai_mode: string } }
type ImportJob = { id: string; label: string }

const STEPS = ['Welcome', 'Privacy', 'AI models', 'Sources', 'Import', 'Memory', 'Finish'] as const

export default function OnboardingPage() {
  const router = useRouter()
  const me = useQuery({ queryKey: ['me'], queryFn: () => get<Me>('/api/auth/me'), retry: false })
  const unauthorized = me.error instanceof ApiError && me.error.status === 401
  useEffect(() => {
    if (unauthorized) router.replace('/login?next=/onboarding')
  }, [unauthorized, router])

  if (me.isLoading || unauthorized) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg">
        <Spinner />
      </div>
    )
  }
  if (me.error || !me.data) {
    return (
      <div className="mx-auto max-w-md pt-24">
        <ErrorState error={me.error} retry={() => me.refetch()} />
      </div>
    )
  }
  return <Flow me={me.data} />
}

function Flow({ me }: { me: Me }) {
  const router = useRouter()
  const qc = useQueryClient()
  const [step, setStep] = useState(0)
  const [jobs, setJobs] = useState<ImportJob[]>([])
  const addJob = (j: ImportJob) => setJobs((js) => (js.some((x) => x.id === j.id) ? js : [...js, j]))

  const complete = useMutation({
    mutationFn: () => post('/api/onboarding/complete', { completed: true }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['me'] })
      router.replace('/')
    },
  })

  const firstName = me.user.display_name?.split(/\s+/)[0]

  return (
    <div className="min-h-screen bg-bg">
      <header className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 pt-6">
        <Wordmark />
        <span className="text-xs text-ink-3">{me.user.email}</span>
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-16 pt-6">
        <Stepper step={step} onJump={(i) => i < step && setStep(i)} />
        <section className="mt-6 rounded-lg border border-line bg-surface shadow-card" aria-labelledby="step-title" key={step}>
          {step === 0 && <Welcome name={firstName} />}
          {step === 1 && <PrivacyStep onNext={() => setStep(2)} onBack={() => setStep(0)} />}
          {step === 2 && <ModelsStep onNext={() => setStep(3)} onBack={() => setStep(1)} />}
          {step === 3 && <SourcesStep />}
          {step === 4 && <ImportStep jobs={jobs} addJob={addJob} />}
          {step === 5 && <MemoryStep jobs={jobs} />}
          {step === 6 && <FinishStep />}
          {/* Steps 1 and 2 own their footer (they save before advancing). */}
          {step !== 1 && step !== 2 && (
            <Footer
              onBack={step > 0 ? () => setStep(step - 1) : undefined}
              next={
                step === 6 ? (
                  <Button variant="primary" loading={complete.isPending} onClick={() => complete.mutate()}>
                    Open Threadline <ArrowRight className="h-4 w-4" />
                  </Button>
                ) : (
                  <Button variant="primary" onClick={() => setStep(step + 1)}>
                    {step === 0 ? 'Get started' : step === 4 && jobs.length === 0 ? 'Skip import' : 'Next'} <ArrowRight className="h-4 w-4" />
                  </Button>
                )
              }
              error={complete.error}
            />
          )}
        </section>
        {step < 6 && (
          <p className="mt-4 text-center text-xs text-ink-3">
            Everything here can be changed later in Settings, Privacy center and Integrations.{' '}
            <button type="button" className="text-accent hover:underline" onClick={() => setStep(6)}>
              Skip to the end
            </button>
          </p>
        )}
      </main>
    </div>
  )
}

function Stepper({ step, onJump }: { step: number; onJump: (i: number) => void }) {
  return (
    <nav aria-label="Setup progress">
      <p className="mb-2 text-xs text-ink-3 sm:hidden">
        Step {step + 1} of {STEPS.length}: {STEPS[step]}
      </p>
      <ol className="flex items-center gap-1.5">
        {STEPS.map((s, i) => {
          const done = i < step
          const current = i === step
          return (
            <li key={s} className="flex min-w-0 flex-1 flex-col gap-1.5">
              <button
                type="button"
                onClick={() => onJump(i)}
                disabled={!done}
                aria-current={current ? 'step' : undefined}
                aria-label={`${s}${done ? ' (completed)' : current ? ' (current)' : ''}`}
                className={cn('h-1 w-full rounded-full transition-colors', done ? 'bg-accent' : current ? 'bg-accent/60' : 'bg-line', done && 'cursor-pointer hover:bg-accent-strong')}
              />
              <span className={cn('hidden truncate text-[11px] sm:block', current ? 'font-medium text-ink' : done ? 'text-ink-2' : 'text-ink-3')}>{s}</span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function StepHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="border-b border-line px-5 py-4">
      <h1 id="step-title" className="font-serif text-[22px] font-medium tracking-tight text-ink">
        {title}
      </h1>
      {children && <div className="mt-1 text-sm text-ink-2">{children}</div>}
    </div>
  )
}

function Footer({ onBack, next, error }: { onBack?: () => void; next: ReactNode; error?: unknown }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3">
      {onBack ? (
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
      ) : (
        <span />
      )}
      <div className="flex items-center gap-3">
        {error ? (
          <span role="alert" className="text-xs text-danger">
            {errorMessage(error)}
          </span>
        ) : null}
        {next}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------------------------------ steps

function Welcome({ name }: { name?: string }) {
  return (
    <>
      <StepHead title={name ? `Welcome, ${name}.` : 'Welcome to Threadline.'}>{TAGLINE}</StepHead>
      <div className="space-y-3 px-5 py-5 text-sm text-ink-2">
        <ul className="space-y-2.5">
          <li className="flex gap-3">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
            <span>
              <span className="font-medium text-ink">Remembers your work.</span> Reads your mail, calendar, documents and notes, and builds a memory of people, projects, decisions and promises.
            </span>
          </li>
          <li className="flex gap-3">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
            <span>
              <span className="font-medium text-ink">Shows its receipts.</span> Every answer, commitment and alert links to the exact source text it came from, with a confidence score.
            </span>
          </li>
          <li className="flex gap-3">
            <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
            <span>
              <span className="font-medium text-ink">Stays on your machine.</span> Data is stored locally and AI runs locally by default. Nothing is sent anywhere unless you allow it.
            </span>
          </li>
        </ul>
        <p className="pt-1 text-xs text-ink-3">Setup takes about two minutes: privacy, models, sources, then an initial import.</p>
      </div>
    </>
  )
}

function PrivacyStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['privacy'], queryFn: () => get<Privacy>('/api/privacy') })
  const [mode, setMode] = useState<AiMode | null>(null)
  const current = mode ?? q.data?.ai_mode ?? 'LOCAL'
  const save = useMutation({
    mutationFn: () => put<Privacy>('/api/privacy', { ai_mode: current }),
    onSuccess: (d) => {
      qc.setQueryData(['privacy'], d)
      qc.invalidateQueries({ queryKey: ['me'] })
      onNext()
    },
  })
  return (
    <>
      <StepHead title="Choose where AI runs">This controls every language-model call. You can change it any time in the Privacy center.</StepHead>
      <div className="space-y-3 px-5 py-5">
        {q.isLoading ? (
          <LoadingRows rows={2} />
        ) : q.error ? (
          <ErrorState error={q.error} retry={() => q.refetch()} />
        ) : (
          <>
            <ModeOptions name="onboarding-mode" value={current} onChange={setMode} />
            <p className="text-xs text-ink-3">
              {q.data?.cloud_configured
                ? `A cloud provider is configured (${q.data.cloud_model}). In Hybrid and Cloud modes it is still used only for sources you mark “Cloud AI allowed”, which is off for every source by default.`
                : 'No cloud provider is configured on this server, so every call runs locally regardless of the mode you pick.'}{' '}
              Sources with “Local AI” turned off are never placed in any prompt. Embeddings are always computed locally.
            </p>
          </>
        )}
      </div>
      <Footer
        onBack={onBack}
        error={save.error}
        next={
          <Button variant="primary" loading={save.isPending} disabled={!q.data} onClick={() => (current === q.data?.ai_mode ? onNext() : save.mutate())}>
            Next <ArrowRight className="h-4 w-4" />
          </Button>
        }
      />
    </>
  )
}

function ModelsStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const qc = useQueryClient()
  const health = useModelsHealth()
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => get<Settings>('/api/settings') })
  const [reasoning, setReasoning] = useState<string | null>(null)
  const [extraction, setExtraction] = useState<string | null>(null)
  const r = reasoning ?? settings.data?.reasoning_model ?? ''
  const e = extraction ?? settings.data?.extraction_model ?? ''
  const dirty = !!settings.data && (r !== settings.data.reasoning_model || e !== settings.data.extraction_model)
  const save = useMutation({
    mutationFn: () => put<Settings>('/api/settings', { reasoning_model: r, extraction_model: e }),
    onSuccess: (d) => {
      qc.setQueryData(['settings'], d)
      onNext()
    },
  })
  const models = health.data?.local.models ?? []
  return (
    <>
      <StepHead title="Configure local AI">Threadline uses a local model runtime (Ollama). Pick which installed models to use.</StepHead>
      <div className="space-y-4 px-5 py-5">
        {health.isLoading || settings.isLoading ? (
          <LoadingRows rows={3} />
        ) : health.error || settings.error || !health.data || !settings.data ? (
          <ErrorState error={health.error ?? settings.error} retry={() => (health.refetch(), settings.refetch())} />
        ) : (
          <>
            <ModelHealthSummary health={health.data} />
            {health.data.local.ok ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <ModelSelect id="ob-reasoning" label="Reasoning model" hint="(answers, briefs)" value={r} models={models} onChange={setReasoning} />
                <ModelSelect id="ob-extraction" label="Extraction model" hint="(optional LLM extraction)" value={e} models={models} onChange={setExtraction} />
              </div>
            ) : (
              <div className="rounded-md border border-warning/30 bg-warning-wash p-3 text-sm text-ink-2">
                <p className="font-medium text-ink">No local models found.</p>
                <p className="mt-1 text-xs">
                  Install Ollama and run <code className="font-mono">ollama pull {settings.data.reasoning_model}</code>. Until then Threadline still works: search, extraction rules and extractive answers with citations need no LLM.
                </p>
                <Button size="sm" className="mt-2" onClick={() => health.refetch()} loading={health.isFetching}>
                  <RefreshCw className="h-3.5 w-3.5" /> Check again
                </Button>
              </div>
            )}
          </>
        )}
      </div>
      <Footer
        onBack={onBack}
        error={save.error}
        next={
          <Button variant="primary" loading={save.isPending} onClick={() => (dirty ? save.mutate() : onNext())}>
            Next <ArrowRight className="h-4 w-4" />
          </Button>
        }
      />
    </>
  )
}

function useIntegrations() {
  return useQuery({ queryKey: ['integrations'], queryFn: () => get<{ items: Integration[] }>('/api/integrations') })
}

function SourcesStep() {
  const [open, setOpen] = useState(false)
  const list = useIntegrations()
  const folders = (list.data?.items ?? []).filter((i) => i.kind === 'local_files' && i.status !== 'revoked')
  return (
    <>
      <StepHead title="Connect sources">Choose what Threadline may read. Connectors marked “Planned” are not available yet.</StepHead>
      <div className="space-y-4 px-5 py-5">
        {folders.length > 0 && (
          <div className="rounded-md border border-line bg-surface-2 p-3">
            <p className="mb-1.5 text-xs font-medium text-ink-2">Folders added</p>
            <ul className="space-y-1">
              {folders.map((f) => (
                <li key={f.id} className="flex items-center gap-2 text-sm text-ink">
                  <FolderOpen className="h-3.5 w-3.5 text-ink-3" /> {f.name}
                  <span className="truncate font-mono text-xs text-ink-3">{String(f.config.path ?? '')}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {list.error ? <ErrorState error={list.error} retry={() => list.refetch()} /> : null}
        <ConnectorCatalog
          compact
          connected={list.data?.items ?? []}
          onLocalFolder={() => setOpen(true)}
          renderDemo={() => <Badge tone="accent">Next step</Badge>}
        />
      </div>
      <LocalFolderDialog open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function ImportStep({ jobs, addJob }: { jobs: ImportJob[]; addJob: (j: ImportJob) => void }) {
  const toast = useToast()
  const list = useIntegrations()
  const folders = (list.data?.items ?? []).filter((i) => i.kind === 'local_files' && i.status !== 'revoked')
  const demo = useMutation({
    mutationFn: () => post<JobStart>('/api/onboarding/demo'),
    onSuccess: (r) => addJob({ id: r.job_id, label: 'Importing the demo workspace' }),
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const sync = useMutation({
    mutationFn: (i: Integration) => post<JobStart>(`/api/integrations/${i.id}/sync`),
    onSuccess: (r, i) => addJob({ id: r.job_id, label: `Syncing ${i.name}` }),
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const demoStarted = jobs.some((j) => j.label.includes('demo'))
  return (
    <>
      <StepHead title="Import data">Bring in something to remember. You can sync more sources later.</StepHead>
      <div className="space-y-4 px-5 py-5">
        <div className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-line p-3">
          <div className="flex min-w-0 gap-3">
            <Database className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" />
            <div>
              <p className="text-sm font-medium text-ink">Demo workspace</p>
              <p className="text-xs text-ink-2">Synthetic emails, meetings, documents and notes for a fictional product team. Safe to explore; delete it any time from Integrations. It also pins a demo clock so dates make sense.</p>
            </div>
          </div>
          <Button variant={demoStarted ? 'secondary' : 'primary'} loading={demo.isPending} disabled={demoStarted} onClick={() => demo.mutate()}>
            {demoStarted ? 'Import started' : 'Import the demo workspace'}
          </Button>
        </div>
        {folders.map((f) => {
          const started = jobs.some((j) => j.label === `Syncing ${f.name}`)
          return (
            <div key={f.id} className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-line p-3">
              <div className="flex min-w-0 gap-3">
                <FolderOpen className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{f.name}</p>
                  <p className="truncate font-mono text-xs text-ink-3">{String(f.config.path ?? '')}</p>
                </div>
              </div>
              <Button variant={started ? 'secondary' : 'primary'} loading={sync.isPending && sync.variables?.id === f.id} disabled={started} onClick={() => sync.mutate(f)}>
                {started ? 'Sync started' : 'Sync this folder'}
              </Button>
            </div>
          )
        })}
        {folders.length === 0 && <p className="text-xs text-ink-3">No local folders connected. Go back to Sources to add one, or import the demo workspace.</p>}
        {jobs.map((j) => (
          <JobProgress key={j.id} jobId={j.id} label={j.label} />
        ))}
      </div>
    </>
  )
}

function MemoryStep({ jobs }: { jobs: ImportJob[] }) {
  const results = useQueries({
    queries: jobs.map((j) => ({
      queryKey: ['job', j.id],
      queryFn: () => get<Job>(`/api/jobs/${j.id}`),
      refetchInterval: (q: { state: { data?: Job } }) => (q.state.data && TERMINAL.has(q.state.data.status) ? false : 1000),
    })),
  })
  const jobsDone = results.every((r) => r.data && TERMINAL.has(r.data.status))
  const queue = useQuery({
    queryKey: ['jobs'],
    queryFn: () => get<JobsResponse>('/api/jobs'),
    refetchInterval: (q) => ((q.state.data?.events.pending ?? 0) > 0 || !jobsDone ? 1500 : false),
  })
  const pendingEvents = queue.data?.events.pending ?? 0
  const ready = jobsDone && queue.data !== undefined && pendingEvents === 0
  const inv = useQuery({ queryKey: ['inventory', ready], queryFn: () => get<Inventory>('/api/privacy/inventory'), enabled: ready })
  const anyFailed = results.some((r) => r.data && (r.data.status === 'dead' || r.data.status === 'failed'))

  const KEYS = ['emails', 'meetings', 'documents', 'notes', 'people', 'organizations', 'commitments', 'decisions', 'tasks', 'memories', 'evidence', 'relationships']
  return (
    <>
      <StepHead title="Build initial memory">Threadline extracts people, projects, commitments and decisions from what was imported, linking each to its evidence.</StepHead>
      <div className="space-y-3 px-5 py-5">
        {jobs.length === 0 ? (
          <p className="text-sm text-ink-2">Nothing was imported, so there is nothing to build yet. Go back to import the demo workspace or a folder, or continue and add sources later.</p>
        ) : (
          <>
            {jobs.map((j) => (
              <JobProgress key={j.id} jobId={j.id} label={j.label} />
            ))}
            {jobsDone && (
              <div className="flex items-center gap-2 text-xs text-ink-2" aria-live="polite">
                {pendingEvents > 0 ? (
                  <>
                    <Spinner className="h-3.5 w-3.5" /> Processing {fmtNum(pendingEvents)} queued item{pendingEvents === 1 ? '' : 's'} into memory…
                  </>
                ) : (
                  <>
                    <Check className="h-3.5 w-3.5 text-success" /> Processing queue is empty.
                  </>
                )}
              </div>
            )}
            {anyFailed && <p className="text-xs text-danger">An import failed. You can retry it later from Integrations; anything already imported is kept.</p>}
          </>
        )}
        {ready && jobs.length > 0 && (
          <div className="rounded-md border border-line bg-surface-2 p-4">
            <p className="mb-3 text-sm font-medium text-ink">Your memory now holds</p>
            {inv.isLoading ? (
              <LoadingRows rows={2} />
            ) : inv.error || !inv.data ? (
              <ErrorState error={inv.error} retry={() => inv.refetch()} />
            ) : (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-4">
                {KEYS.filter((k) => k in inv.data.counts).map((k) => (
                  <div key={k}>
                    <dt className="text-xs text-ink-3">{humanize(k)}</dt>
                    <dd className="text-lg font-semibold tabular-nums text-ink">{fmtNum(inv.data.counts[k])}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        )}
      </div>
    </>
  )
}

function FinishStep() {
  const privacy = useQuery({ queryKey: ['privacy'], queryFn: () => get<Privacy>('/api/privacy') })
  const list = useIntegrations()
  const sources = (list.data?.items ?? []).filter((i) => i.status !== 'revoked' && i.kind !== 'notes' && i.kind !== 'uploads')
  return (
    <>
      <StepHead title="You’re set up">Here is how Threadline is configured.</StepHead>
      <div className="px-5 py-5">
        <dl className="divide-y divide-line rounded-md border border-line text-sm">
          <div className="flex justify-between gap-3 px-3 py-2">
            <dt className="text-ink-3">AI mode</dt>
            <dd className="font-medium text-ink">{privacy.data ? (privacy.data.ai_mode === 'LOCAL' ? 'Local only' : humanize(privacy.data.ai_mode.toLowerCase())) : '…'}</dd>
          </div>
          <div className="flex justify-between gap-3 px-3 py-2">
            <dt className="text-ink-3">Sources</dt>
            <dd className="text-right font-medium text-ink">{list.data ? (sources.length ? sources.map((s) => s.name).join(', ') : 'None yet') : '…'}</dd>
          </div>
          <div className="flex justify-between gap-3 px-3 py-2">
            <dt className="text-ink-3">Where data lives</dt>
            <dd className="text-right text-ink">{privacy.data?.stored_at ?? '…'}</dd>
          </div>
        </dl>
        <p className="mt-4 text-xs text-ink-3">Try asking the assistant “What did I promise this week?” or open the dashboard for today’s briefing.</p>
      </div>
    </>
  )
}
