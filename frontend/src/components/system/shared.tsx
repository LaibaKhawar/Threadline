'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Cloud, HardDrive, Layers } from 'lucide-react'
import { type ReactNode, useState } from 'react'

import { useToast } from '@/components/toast'
import { Badge, Button, Dialog, Input, Label } from '@/components/ui/primitives'
import { errorMessage, post } from '@/lib/api'
import type { AiMode, Integration, Job } from '@/lib/types-system'
import { cn } from '@/lib/utils'

import { useJob } from './use-job'

// ------------------------------------------------------------------------------------------ formatting

export const fmtNum = (n: number | null | undefined) => (n === null || n === undefined ? '—' : n.toLocaleString('en-US'))
export const fmtMs = (n: number | null | undefined) => (n === null || n === undefined ? '—' : n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`)
export const fmtUsd = (n: number | null | undefined) => {
  if (!n) return '$0.00'
  return n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`
}
const LABELS: Record<string, string> = { llm_calls: 'LLM calls', agent_runs: 'Assistant runs', audit_log: 'Audit log entries', qa: 'QA', temporal_qa: 'Temporal QA', agent_tools: 'Agent tools' }
export const humanize = (s: string) => LABELS[s] ?? s.replace(/[_:]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** Local wall-clock formatting (activity logs are real timestamps, not the demo clock). */
export function fmtStamp(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

// ------------------------------------------------------------------------------------------ tables

export const th = 'px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-ink-3 whitespace-nowrap'
export const td = 'px-3 py-2 align-top text-sm text-ink-2'

export function Table({ children, label, className }: { children: ReactNode; label: string; className?: string }) {
  return (
    <div className={cn('overflow-x-auto scrollbar-thin', className)}>
      <table className="w-full min-w-full border-collapse" aria-label={label}>
        {children}
      </table>
    </div>
  )
}

// ------------------------------------------------------------------------------------------ privacy copy

export const AI_MODES: { value: AiMode; label: string; short: string; detail: string[]; icon: ReactNode }[] = [
  {
    value: 'LOCAL',
    label: 'Local only',
    short: 'Every AI call runs on this machine.',
    detail: ['Zero cloud LLM calls, whatever else is set.', 'Uses your local Ollama models; embeddings are local too.', 'Recommended default.'],
    icon: <HardDrive className="h-4 w-4" />,
  },
  {
    value: 'HYBRID',
    label: 'Hybrid',
    short: 'Cloud only for operations you allow-list.',
    detail: [
      'An operation goes to the cloud model only if you allow-listed it AND every source in that prompt allows cloud AI.',
      'Everything else runs locally.',
    ],
    icon: <Layers className="h-4 w-4" />,
  },
  {
    value: 'CLOUD',
    label: 'Cloud',
    short: 'Configured cloud provider where sources allow it.',
    detail: ['Uses the configured cloud provider when every source in the prompt allows cloud AI.', 'Otherwise (including in-app notes) the call stays local.'],
    icon: <Cloud className="h-4 w-4" />,
  },
]

export const OPERATION_LABEL: Record<string, string> = {
  answer_synthesis: 'Assistant answers',
  meeting_brief: 'Meeting briefs',
  summarize: 'Summaries',
  extraction: 'Extraction (commitments, decisions, entities)',
  planning: 'Assistant planning',
  briefing: 'Daily briefing',
}

export function ModeOptions({ value, onChange, disabled, name }: { value: AiMode; onChange: (m: AiMode) => void; disabled?: boolean; name: string }) {
  return (
    <div role="radiogroup" aria-label="AI mode" className="grid gap-2 sm:grid-cols-3">
      {AI_MODES.map((m) => {
        const active = value === m.value
        return (
          <label
            key={m.value}
            className={cn(
              'flex cursor-pointer flex-col gap-1.5 rounded-md border p-3 transition-colors focus-within:ring-2 focus-within:ring-[var(--accent-ring)]',
              active ? 'border-accent bg-accent-wash' : 'border-line bg-surface hover:bg-sunken',
              disabled && 'cursor-not-allowed opacity-60',
            )}
          >
            <span className="flex items-center gap-2">
              <input type="radio" name={name} className="sr-only" checked={active} disabled={disabled} onChange={() => onChange(m.value)} />
              <span className={cn('text-ink-3', active && 'text-accent')}>{m.icon}</span>
              <span className="text-sm font-medium text-ink">{m.label}</span>
              {m.value === 'LOCAL' && <Badge tone="success">Default</Badge>}
            </span>
            <span className="text-xs text-ink-2">{m.short}</span>
            <ul className="space-y-0.5">
              {m.detail.map((d) => (
                <li key={d} className="text-[11px] leading-4 text-ink-3">
                  · {d}
                </li>
              ))}
            </ul>
          </label>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------------------------------------ jobs

export function JobStatusBadge({ status }: { status: string }) {
  const tone = status === 'succeeded' ? 'success' : status === 'dead' || status === 'failed' ? 'danger' : status === 'running' ? 'info' : 'neutral'
  const label = status === 'dead' ? 'Failed' : status.charAt(0).toUpperCase() + status.slice(1)
  return <Badge tone={tone}>{label}</Badge>
}

export function ProgressBar({ percent, label }: { percent?: number; label: string }) {
  const indeterminate = percent === undefined || percent < 1
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : percent}
      className="relative h-1.5 w-full overflow-hidden rounded-full bg-sunken"
    >
      <div className={cn('absolute inset-y-0 left-0 rounded-full bg-accent transition-all', indeterminate && 'w-1/3 animate-pulse')} style={indeterminate ? undefined : { width: `${percent}%` }} />
    </div>
  )
}

function summarizeResult(r: Record<string, unknown> | undefined) {
  if (!r) return null
  const parts = Object.entries(r)
    .filter(([k, v]) => k !== 'ok' && (typeof v === 'number' || typeof v === 'boolean'))
    .slice(0, 6)
    .map(([k, v]) => `${humanize(k)}: ${typeof v === 'number' ? fmtNum(v) : v ? 'yes' : 'no'}`)
  return parts.length ? parts.join(' · ') : null
}

/** Live progress for one background job (polls until finished). */
export function JobProgress({ jobId, label, onDone, className }: { jobId: string | null | undefined; label: string; onDone?: (j: Job) => void; className?: string }) {
  const j = useJob(jobId, { onDone })
  if (!jobId) return null
  const status = j.job?.status ?? 'queued'
  return (
    <div className={cn('rounded-md border border-line bg-surface-2 p-3', className)} aria-live="polite">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm text-ink">
          {j.isDone ? <CheckCircle2 className="h-4 w-4 text-success" /> : j.isFailed ? <AlertTriangle className="h-4 w-4 text-danger" /> : null}
          {label}
        </span>
        <JobStatusBadge status={status} />
      </div>
      {!j.isFailed && <ProgressBar percent={j.percent} label={label} />}
      <div className="mt-1.5 text-xs text-ink-3">
        {j.isFailed ? (
          <span className="text-danger">{j.job?.error ?? 'The job failed.'}</span>
        ) : j.isDone ? (
          (summarizeResult(j.job?.progress?.result) ?? 'Finished.')
        ) : (
          <>
            {j.message ? humanize(j.message) : status === 'queued' ? 'Waiting to start…' : 'Working…'}
            {j.percent !== undefined && j.percent > 0 ? ` · ${j.percent}%` : ''}
            {j.job && j.job.attempts > 1 ? ` · attempt ${j.job.attempts}` : ''}
          </>
        )}
      </div>
      {j.error ? <p className="mt-1 text-xs text-danger">{errorMessage(j.error)}</p> : null}
    </div>
  )
}

// ------------------------------------------------------------------------------------------ dialogs

export function ConfirmDialog({
  open,
  onClose,
  title,
  children,
  confirmLabel,
  onConfirm,
  pending,
  requireText,
  error,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  confirmLabel: string
  onConfirm: () => void
  pending?: boolean
  requireText?: string
  error?: unknown
}) {
  const [typed, setTyped] = useState('')
  const close = () => {
    setTyped('')
    onClose()
  }
  const ok = !requireText || typed === requireText
  return (
    <Dialog
      open={open}
      onClose={close}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button variant="danger" disabled={!ok} loading={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm text-ink-2">
        {children}
        {requireText && (
          <div>
            <Label htmlFor="confirm-text">
              Type <span className="font-mono font-semibold text-ink">{requireText}</span> to confirm
            </Label>
            <Input id="confirm-text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} />
          </div>
        )}
        {error ? (
          <p role="alert" className="text-xs text-danger">
            {errorMessage(error)}
          </p>
        ) : null}
      </div>
    </Dialog>
  )
}

/** Add a local folder source (POST /api/integrations {kind:'local_files', config:{path}}). */
export function LocalFolderDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated?: (i: Integration) => void }) {
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const qc = useQueryClient()
  const toast = useToast()
  const create = useMutation({
    mutationFn: () => post<Integration>('/api/integrations', { kind: 'local_files', name: name.trim() || undefined, config: { path: path.trim() } }),
    onSuccess: (i) => {
      qc.invalidateQueries({ queryKey: ['integrations'] })
      qc.invalidateQueries({ queryKey: ['privacy'] })
      toast(`Connected ${i.name}. Run a sync to import it.`)
      setPath('')
      setName('')
      onCreated?.(i)
      onClose()
    },
  })
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add a local folder"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!path.trim()} loading={create.isPending} onClick={() => create.mutate()}>
            Add folder
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (path.trim()) create.mutate()
        }}
      >
        <div>
          <Label htmlFor="folder-path" hint="(absolute path on the machine running Threadline)">
            Folder path
          </Label>
          <Input id="folder-path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/Users/you/Documents/work" autoComplete="off" spellCheck={false} />
        </div>
        <div>
          <Label htmlFor="folder-name" hint="(optional)">
            Display name
          </Label>
          <Input id="folder-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Local folder" />
        </div>
        <p className="text-xs text-ink-3">
          Indexes PDF, DOCX, TXT, Markdown, CSV, XLSX, .eml/.mbox mail and .ics calendars. Files are read in place and never uploaded anywhere. Re-syncs only process changed files.
        </p>
        {create.error ? (
          <p role="alert" className="text-xs text-danger">
            {errorMessage(create.error)}
          </p>
        ) : null}
      </form>
    </Dialog>
  )
}

/** Compact switch for table cells (label is announced, not shown). */
export function MiniSwitch({ checked, onChange, label, disabled, title }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; title?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={title ?? label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn('relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40', checked ? 'bg-accent' : 'bg-line-strong')}
    >
      <span aria-hidden className={cn('absolute left-0 top-0.5 h-4 w-4 rounded-full bg-surface shadow transition-transform', checked ? 'translate-x-[18px]' : 'translate-x-0.5')} />
    </button>
  )
}

/** Labelled switch row (visible label + description) built on MiniSwitch. */
export function SwitchRow({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: ReactNode; disabled?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="text-sm text-ink">{label}</div>
        {description && <p className="text-xs text-ink-3">{description}</p>}
      </div>
      <MiniSwitch checked={checked} onChange={onChange} label={label} disabled={disabled} />
    </div>
  )
}
