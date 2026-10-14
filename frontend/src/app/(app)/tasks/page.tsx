'use client'

import { useQuery } from '@tanstack/react-query'
import { CheckSquare, Sparkles } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { Suspense } from 'react'

import { Card, CardHeader, EmptyState, ErrorState, LoadingRows, PageHeader, Select, Switch } from '@/components/ui/primitives'
import { DueText, ProjectTag, Segmented, useProjects, useWorkMutation } from '@/components/work/shared'
import { NewTaskButton, PriorityDot, SuggestionActions, SuggestionProvenance, TaskInlineEdit } from '@/components/work/tasks'
import { get, put } from '@/lib/api'
import type { Task } from '@/lib/types'
import type { TaskList } from '@/lib/types-work'
import { cn } from '@/lib/utils'

export default function TasksPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <TasksView />
    </Suspense>
  )
}

type View = 'board' | 'list' | 'suggested'

const COLUMNS: { status: Task['status']; title: string; hint: string }[] = [
  { status: 'suggested', title: 'AI suggestions', hint: 'Found in your email and meetings. Confirm to make them tasks.' },
  { status: 'active', title: 'Active', hint: 'In progress or to do.' },
  { status: 'blocked', title: 'Blocked', hint: 'Waiting on someone or something.' },
  { status: 'done', title: 'Done', hint: 'Completed.' },
]

function TasksView() {
  const sp = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const view = (['board', 'list', 'suggested'].includes(sp.get('view') ?? '') ? sp.get('view') : 'board') as View
  const project = sp.get('project') ?? ''
  const projects = useProjects()
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp.toString())
    if (v && !(k === 'view' && v === 'board')) next.set(k, v)
    else next.delete(k)
    router.replace(`${pathname}${next.toString() ? `?${next}` : ''}`, { scroll: false })
  }
  const q = useQuery({
    queryKey: ['tasks', 'list', project],
    queryFn: () => get<TaskList>(`/api/tasks${project ? `?project_id=${project}` : ''}`),
  })
  const items = (q.data?.items ?? []).filter((t) => t.status !== 'dismissed')
  const suggestions = items.filter((t) => t.status === 'suggested')
  const now = q.data?.now

  return (
    <div>
      <PageHeader
        title="Tasks"
        description="Your tasks, plus suggestions Threadline found in email and meetings. Suggestions never become tasks without you, unless you turn on auto-create."
        actions={<NewTaskButton defaultProjectId={project || undefined} />}
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Segmented
          label="View"
          value={view}
          onChange={(v) => setParam('view', v)}
          options={[
            { value: 'board', label: 'Board' },
            { value: 'list', label: 'List' },
            {
              value: 'suggested',
              label: (
                <>
                  <Sparkles className="h-3 w-3 text-uncertain" aria-hidden /> Suggestions
                </>
              ),
              count: suggestions.length,
            },
          ]}
        />
        <div className="flex items-center gap-2">
          <label htmlFor="tasks-project" className="sr-only">
            Project
          </label>
          <Select id="tasks-project" value={project} onChange={(e) => setParam('project', e.target.value)}>
            <option value="">All projects</option>
            {projects.data?.items.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {q.isLoading ? (
        <Card>
          <LoadingRows rows={8} />
        </Card>
      ) : q.error || !q.data ? (
        <Card>
          <ErrorState error={q.error} retry={() => q.refetch()} />
        </Card>
      ) : view === 'suggested' ? (
        <div className="space-y-4">
          <AutoCreate enabled={q.data.auto_create} />
          <Card>
            <CardHeader title="AI suggestions to review" description="Each one shows the sentence it came from and how confident the extractor was." />
            {suggestions.length === 0 ? (
              <EmptyState icon={<Sparkles className="h-4 w-4" />} title="No suggestions waiting" description="New ones appear when Threadline finds something you said you would do." />
            ) : (
              <ul className="divide-y divide-line">
                {suggestions.map((t) => (
                  <li key={t.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-ink">{t.title}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                          <ProjectTag project={t.project} />
                          <DueText due={t.due_at} now={now} />
                        </div>
                        <div className="mt-2">
                          <SuggestionProvenance task={t} />
                        </div>
                      </div>
                      <SuggestionActions task={t} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState icon={<CheckSquare className="h-4 w-4" />} title="No tasks yet" description="Create one, or wait for suggestions from your email and meetings." action={<NewTaskButton />} />
        </Card>
      ) : view === 'board' ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {COLUMNS.map((col) => {
              const list = items.filter((t) => t.status === col.status)
              return (
                <section key={col.status} aria-label={col.title} className={cn('flex min-w-0 flex-col rounded-lg border border-line', col.status === 'suggested' ? 'bg-uncertain-wash/40' : 'bg-bg-2')}>
                  <header className="px-3 pb-2 pt-3">
                    <h2 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
                      {col.status === 'suggested' && <Sparkles className="h-3.5 w-3.5 text-uncertain" aria-hidden />}
                      {col.title}
                      <span className="text-xs font-normal tabular-nums text-ink-3">{list.length}</span>
                    </h2>
                    <p className="text-[11px] text-ink-3">{col.hint}</p>
                  </header>
                  <ul className="flex-1 space-y-2 px-2 pb-2">
                    {list.length === 0 && <li className="rounded-md border border-dashed border-line px-3 py-4 text-center text-xs text-ink-3">Empty</li>}
                    {list.map((t) => (
                      <li key={t.id}>
                        <BoardCard t={t} now={now} />
                      </li>
                    ))}
                  </ul>
                </section>
              )
            })}
          </div>
          <div className="mt-5">
            <AutoCreate enabled={q.data.auto_create} />
          </div>
        </>
      ) : (
        <>
          <Card>
            <ul className="divide-y divide-line">
              {[...items].sort(sortForList).map((t) => (
                <li key={t.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <PriorityDot priority={t.priority} />
                      <span className={cn('text-sm', t.status === 'done' ? 'text-ink-3 line-through' : 'text-ink')}>{t.title}</span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 pl-3.5 text-xs">
                      <ProjectTag project={t.project} />
                      <DueText due={t.due_at} now={now} done={t.status === 'done'} />
                      {t.blocked_reason && <span className="text-danger">Blocked: {t.blocked_reason}</span>}
                    </div>
                    {t.status === 'suggested' && (
                      <div className="mt-1.5 pl-3.5">
                        <SuggestionProvenance task={t} />
                      </div>
                    )}
                  </div>
                  {t.status === 'suggested' ? <SuggestionActions task={t} /> : <TaskInlineEdit task={t} />}
                </li>
              ))}
            </ul>
          </Card>
          <div className="mt-5">
            <AutoCreate enabled={q.data.auto_create} />
          </div>
        </>
      )}
    </div>
  )
}

const ORDER: Record<string, number> = { suggested: 0, blocked: 1, active: 2, done: 3 }
function sortForList(a: Task, b: Task) {
  return (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9) || (a.due_at ?? '9').localeCompare(b.due_at ?? '9')
}

function BoardCard({ t, now }: { t: Task; now: string | undefined }) {
  const suggested = t.status === 'suggested'
  return (
    <article className={cn('rounded-md border bg-surface p-3 shadow-card', suggested ? 'border-uncertain/30' : 'border-line')}>
      <div className="flex items-start gap-2">
        <PriorityDot priority={t.priority} />
        <h3 className={cn('-mt-1 text-sm', t.status === 'done' ? 'text-ink-3 line-through' : 'text-ink')}>{t.title}</h3>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 pl-3.5 text-xs">
        <ProjectTag project={t.project} />
        <DueText due={t.due_at} now={now} done={t.status === 'done'} />
      </div>
      {t.blocked_reason && <p className="mt-1 pl-3.5 text-xs text-danger">{t.blocked_reason}</p>}
      <div className="mt-2.5 border-t border-line pt-2.5">
        {suggested ? (
          <div className="space-y-2">
            <SuggestionProvenance task={t} />
            <SuggestionActions task={t} />
          </div>
        ) : (
          <TaskInlineEdit task={t} />
        )}
      </div>
    </article>
  )
}

function AutoCreate({ enabled }: { enabled: boolean }) {
  const m = useWorkMutation(
    (v: boolean) => put<{ auto_create: boolean }>('/api/tasks/settings/auto-create', { enabled: v }),
    (r) => (r.auto_create ? 'Auto-create on: new suggestions become active tasks' : 'Auto-create off: suggestions wait for your confirmation'),
  )
  return (
    <Card className="px-4 py-3">
      <Switch
        checked={m.isPending ? !!m.variables : enabled}
        disabled={m.isPending}
        onChange={(v) => m.mutate(v)}
        label="Create tasks automatically"
        description="Off by default: AI suggestions wait for you to confirm them. When on, newly detected tasks are added as active straight away (still labelled as AI-created, with their source). Existing suggestions are not changed."
      />
    </Card>
  )
}
