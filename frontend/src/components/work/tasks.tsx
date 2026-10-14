'use client'

import { Check, Plus, X } from 'lucide-react'
import { useId, useState } from 'react'

import { AiLabel, Confidence, EvidenceChip } from '@/components/ui/ai'
import { Button, Dialog, Input, Label, Select, Textarea } from '@/components/ui/primitives'
import { patch, post } from '@/lib/api'
import type { Task } from '@/lib/types'
import { cn, fmtDate } from '@/lib/utils'

import { DueText, ProjectTag, fromDateInput, toDateInput, useProjects, useWorkMutation } from './shared'

type TaskPatch = Partial<{ status: Task['status']; priority: Task['priority']; due_at: string; clear_due: boolean; title: string; project_id: string | null }>

const STATUS_TEXT: Record<string, string> = { active: 'Active', blocked: 'Blocked', done: 'Done', suggested: 'Suggestion', dismissed: 'Dismissed' }

export function useTaskPatch() {
  return useWorkMutation(
    ({ id, body }: { id: string; body: TaskPatch }) => patch<Task>(`/api/tasks/${id}`, body),
    (t, v) =>
      v.body.status === 'active' && 'status' in v.body
        ? `“${t.title}” is now active`
        : v.body.status === 'dismissed'
          ? `Dismissed “${t.title}”`
          : v.body.status
            ? `Moved to ${STATUS_TEXT[v.body.status]}`
            : v.body.priority
              ? `Priority set to ${v.body.priority}`
              : v.body.clear_due
                ? 'Due date cleared'
                : v.body.due_at
                  ? `Due ${fmtDate(v.body.due_at)}`
                  : 'Task updated',
  )
}

/** Confirm / Dismiss for an AI-suggested task. */
export function SuggestionActions({ task, size = 'sm' }: { task: Task; size?: 'sm' | 'md' }) {
  const m = useTaskPatch()
  const busy = m.isPending
  return (
    <div className="flex gap-1">
      <Button size={size} variant="secondary" disabled={busy} loading={busy && m.variables?.body.status === 'active'} onClick={() => m.mutate({ id: task.id, body: { status: 'active' } })} aria-label={`Confirm task: ${task.title}`}>
        <Check className="h-3 w-3" /> Confirm
      </Button>
      <Button size={size} variant="ghost" disabled={busy} loading={busy && m.variables?.body.status === 'dismissed'} onClick={() => m.mutate({ id: task.id, body: { status: 'dismissed' } })} aria-label={`Dismiss suggestion: ${task.title}`}>
        <X className="h-3 w-3" /> Dismiss
      </Button>
    </div>
  )
}

/** Why the AI suggested this task: label, confidence and the exact source span. */
export function SuggestionProvenance({ task }: { task: Task }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <AiLabel>AI suggestion</AiLabel>
      <Confidence value={task.confidence} label="suggestion confidence" />
      {task.source && <EvidenceChip type={task.source.type} id={task.source.id} span={task.source.span} label={task.source.span ? `“${task.source.span.slice(0, 48)}${task.source.span.length > 48 ? '…' : ''}”` : 'Source'} />}
    </div>
  )
}

/** Inline editors for status, priority and due date. Each change is a PATCH. */
export function TaskInlineEdit({ task, compact }: { task: Task; compact?: boolean }) {
  const m = useTaskPatch()
  const sid = useId()
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', m.isPending && 'opacity-60')}>
      <label htmlFor={`${sid}-s`} className="sr-only">
        Status
      </label>
      <Select id={`${sid}-s`} className="h-7 px-1.5 text-xs" value={task.status} disabled={m.isPending} onChange={(e) => m.mutate({ id: task.id, body: { status: e.target.value as Task['status'] } })}>
        {task.status === 'suggested' && <option value="suggested">Suggestion</option>}
        <option value="active">Active</option>
        <option value="blocked">Blocked</option>
        <option value="done">Done</option>
        {task.status === 'dismissed' && <option value="dismissed">Dismissed</option>}
      </Select>
      <label htmlFor={`${sid}-p`} className="sr-only">
        Priority
      </label>
      <Select id={`${sid}-p`} className="h-7 px-1.5 text-xs" value={task.priority} disabled={m.isPending} onChange={(e) => m.mutate({ id: task.id, body: { priority: e.target.value as Task['priority'] } })}>
        <option value="low">Low</option>
        <option value="medium">Medium</option>
        <option value="high">High</option>
        <option value="urgent">Urgent</option>
      </Select>
      {!compact && (
        <>
          <label htmlFor={`${sid}-d`} className="sr-only">
            Due date
          </label>
          <input
            id={`${sid}-d`}
            type="date"
            className="h-7 rounded-md border border-line bg-surface px-1.5 text-xs text-ink focus:border-accent focus:outline-none"
            value={toDateInput(task.due_at)}
            disabled={m.isPending}
            onChange={(e) => m.mutate({ id: task.id, body: e.target.value ? { due_at: fromDateInput(e.target.value) } : { clear_due: true } })}
          />
        </>
      )}
    </div>
  )
}

const PRIORITY_DOT: Record<string, string> = { urgent: 'bg-danger', high: 'bg-warning', medium: 'bg-info', low: 'bg-line-strong' }

export function PriorityDot({ priority }: { priority: string }) {
  return <span className={cn('inline-block h-1.5 w-1.5 shrink-0 rounded-full', PRIORITY_DOT[priority] ?? 'bg-line-strong')} title={`${priority} priority`} aria-label={`${priority} priority`} />
}

/** A compact task line used inside thread and project views. */
export function TaskLine({ task, now, showProject = true }: { task: Task; now: string | undefined; showProject?: boolean }) {
  const suggested = task.status === 'suggested'
  return (
    <div className="py-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <PriorityDot priority={task.priority} />
          <span className={cn('text-sm', task.status === 'done' ? 'text-ink-3 line-through' : 'text-ink')}>{task.title}</span>
        </div>
        {!suggested && <span className="shrink-0 text-[11px] text-ink-3">{STATUS_TEXT[task.status]}</span>}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 pl-3.5 text-xs">
        {showProject && <ProjectTag project={task.project} />}
        <DueText due={task.due_at} now={now} done={task.status === 'done'} />
        {task.blocked_reason && <span className="text-danger">Blocked: {task.blocked_reason}</span>}
      </div>
      {suggested && (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 pl-3.5">
          <SuggestionProvenance task={task} />
          <SuggestionActions task={task} />
        </div>
      )}
    </div>
  )
}

export function NewTaskButton({ defaultProjectId, variant = 'primary' }: { defaultProjectId?: string; variant?: 'primary' | 'secondary' }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant={variant} onClick={() => setOpen(true)}>
        <Plus className="h-3.5 w-3.5" /> New task
      </Button>
      {open && <NewTaskDialog onClose={() => setOpen(false)} defaultProjectId={defaultProjectId} />}
    </>
  )
}

function NewTaskDialog({ onClose, defaultProjectId }: { onClose: () => void; defaultProjectId?: string }) {
  const projects = useProjects()
  const id = useId()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [projectId, setProjectId] = useState(defaultProjectId ?? '')
  const [priority, setPriority] = useState<Task['priority']>('medium')
  const [due, setDue] = useState('')
  const [status, setStatus] = useState<'active' | 'blocked' | 'done'>('active')
  const m = useWorkMutation(
    () =>
      post<Task>('/api/tasks', {
        title: title.trim(),
        description: description.trim() || null,
        project_id: projectId || null,
        priority,
        status,
        due_at: due ? fromDateInput(due) : null,
      }),
    (t) => `Created “${t.title}”`,
  )
  const submit = () => title.trim() && m.mutate(undefined, { onSuccess: onClose })
  return (
    <Dialog
      open
      onClose={onClose}
      title="New task"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={!title.trim()} loading={m.isPending}>
            Create task
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div>
          <Label htmlFor={`${id}-t`}>Title</Label>
          <Input id={`${id}-t`} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus required maxLength={500} placeholder="What needs doing?" />
        </div>
        <div>
          <Label htmlFor={`${id}-d`} hint="optional">
            Description
          </Label>
          <Textarea id={`${id}-d`} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor={`${id}-p`}>Project</Label>
            <Select id={`${id}-p`} className="w-full" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">No project</option>
              {projects.data?.items.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor={`${id}-due`}>Due</Label>
            <Input id={`${id}-due`} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
          <div>
            <Label htmlFor={`${id}-pr`}>Priority</Label>
            <Select id={`${id}-pr`} className="w-full" value={priority} onChange={(e) => setPriority(e.target.value as Task['priority'])}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </Select>
          </div>
          <div>
            <Label htmlFor={`${id}-st`}>Status</Label>
            <Select id={`${id}-st`} className="w-full" value={status} onChange={(e) => setStatus(e.target.value as 'active' | 'blocked' | 'done')}>
              <option value="active">Active</option>
              <option value="blocked">Blocked</option>
              <option value="done">Done</option>
            </Select>
          </div>
        </div>
        <button type="submit" className="hidden" aria-hidden tabIndex={-1} />
      </form>
    </Dialog>
  )
}
