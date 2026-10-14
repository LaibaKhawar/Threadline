'use client'

import { Pencil, X } from 'lucide-react'
import { useId, useState } from 'react'

import { AiLabel, Confidence, InferenceCard } from '@/components/ui/ai'
import { Button, Dialog, Label, Select } from '@/components/ui/primitives'
import { post } from '@/lib/api'
import type { InferenceAction, ThreadInference } from '@/lib/types-work'

import { useProjects, useWorkMutation } from './shared'

const DONE_LABEL: Record<string, string> = { confirmed: 'Confirmed by you', changed: 'Changed by you', rejected: 'Ignored by you' }

/** A project-association inference with Confirm / Change / Ignore wired to POST /api/inferences/{id}. */
export function ProjectInference({ inf, context }: { inf: ThreadInference; context?: string }) {
  const [changing, setChanging] = useState(false)
  const m = useWorkMutation(
    (body: InferenceAction) => post<{ ok: boolean; status: string; project_id: string | null }>(`/api/inferences/${inf.id}`, body),
    (_r, v) => (v.action === 'confirm' ? `Linked to ${inf.value_label}` : v.action === 'reject' ? 'Project link removed' : 'Project changed'),
  )
  const dialog = (
    <ChangeProjectDialog
      open={changing}
      current={inf.value_id}
      busy={m.isPending}
      onClose={() => setChanging(false)}
      onSave={(pid) => m.mutate({ action: 'change', project_id: pid }, { onSuccess: () => setChanging(false) })}
    />
  )
  if (inf.status === 'auto') {
    // applied automatically because confidence was high; still inspectable and correctable
    return (
      <div className="rounded-md border border-line px-3 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <AiLabel>Filed automatically</AiLabel>
            <span className="font-medium text-ink">{inf.value_label}</span>
            <Confidence value={inf.confidence} />
          </div>
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" disabled={m.isPending} onClick={() => setChanging(true)}>
              <Pencil className="h-3 w-3" /> Change
            </Button>
            <Button size="sm" variant="ghost" disabled={m.isPending} onClick={() => m.mutate({ action: 'reject' })} aria-label={`Remove link to ${inf.value_label}`}>
              <X className="h-3 w-3" /> Remove
            </Button>
          </div>
        </div>
        <ul className="mt-1 space-y-0.5 text-[11px] text-ink-3">
          {[...(context ? [context] : []), ...inf.reasons].map((r) => (
            <li key={r}>· {r}</li>
          ))}
        </ul>
        {dialog}
      </div>
    )
  }
  if (inf.status !== 'pending') {
    return (
      <div className="rounded-md border border-line px-3 py-2 text-xs text-ink-2">
        <span className="text-ink-3">{DONE_LABEL[inf.status] ?? inf.status}:</span> {inf.status === 'rejected' ? `not ${inf.value_label}` : inf.value_label}
        {context && <span className="text-ink-3"> · {context}</span>}
      </div>
    )
  }
  return (
    <div>
      <InferenceCard
        label="Project"
        value={inf.value_label ?? 'None'}
        confidence={inf.confidence}
        reasons={[...(context ? [context] : []), ...inf.reasons]}
        busy={m.isPending}
        onConfirm={() => m.mutate({ action: 'confirm' })}
        onChange={() => setChanging(true)}
        onIgnore={() => m.mutate({ action: 'reject' })}
      />
      {dialog}
    </div>
  )
}

export function ChangeProjectDialog({ open, current, onClose, onSave, busy }: { open: boolean; current: string | null; onClose: () => void; onSave: (pid: string) => void; busy?: boolean }) {
  const projects = useProjects()
  const [pid, setPid] = useState<string>('')
  const id = useId()
  const value = pid || current || ''
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Change project"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!value} loading={busy} onClick={() => value && onSave(value)}>
            Save
          </Button>
        </>
      }
    >
      <Label htmlFor={id}>Project</Label>
      <Select id={id} className="w-full" value={value} onChange={(e) => setPid(e.target.value)} disabled={projects.isLoading}>
        <option value="" disabled>
          {projects.isLoading ? 'Loading projects…' : 'Choose a project'}
        </option>
        {projects.data?.items.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </Select>
      <p className="mt-2 text-xs text-ink-3">The whole thread moves to this project. Your choice is remembered and outranks the model on later passes.</p>
    </Dialog>
  )
}
