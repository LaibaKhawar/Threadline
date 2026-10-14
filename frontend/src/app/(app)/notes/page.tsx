'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, NotebookPen, Pin, Plus, Save, Search, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'

import { NoteMarkdown, wikiLinks } from '@/components/memory/note-markdown'
import { useWorkspaceNow } from '@/components/memory/use-now'
import { useToast } from '@/components/toast'
import { AiLabel, Avatar, Confidence, InferenceCard, ProjectChip } from '@/components/ui/ai'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Input, Kbd, Label, LoadingRows, PageHeader, Select, Tabs, Textarea } from '@/components/ui/primitives'
import { errorMessage, get, post, put, del } from '@/lib/api'
import type { Note, ProjectSummary } from '@/lib/types'
import type { InferenceItem, NoteDetail, NoteInput } from '@/lib/types-memory'
import { cn, relDays } from '@/lib/utils'

export default function NotesPage() {
  return (
    <Suspense fallback={<LoadingRows rows={6} />}>
      <NotesApp />
    </Suspense>
  )
}

function NotesApp() {
  const params = useSearchParams()
  const router = useRouter()
  const qc = useQueryClient()
  const toast = useToast()
  const now = useWorkspaceNow()
  const id = params.get('id')
  const [q, setQ] = useState('')
  const [tag, setTag] = useState('')
  const dq = useDeferredValue(q.trim())
  const dirty = useRef(false)

  const all = useQuery({ queryKey: ['notes', '', ''], queryFn: () => get<{ items: Note[] }>('/api/notes') })
  const list = useQuery({
    queryKey: ['notes', dq, tag],
    queryFn: () => {
      const p = new URLSearchParams()
      if (dq) p.set('q', dq)
      if (tag) p.set('tag', tag)
      return get<{ items: Note[] }>(`/api/notes${p.size ? `?${p}` : ''}`)
    },
    placeholderData: (prev) => prev,
  })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => get<{ items: ProjectSummary[] }>('/api/projects') })
  const note = useQuery({ queryKey: ['note', id], queryFn: () => get<NoteDetail>(`/api/notes/${id}`), enabled: !!id && id !== 'new' })

  const allTags = useMemo(() => Array.from(new Set((all.data?.items ?? []).flatMap((n) => n.tags))).sort(), [all.data])

  const go = useCallback(
    (next: string | null) => {
      if (dirty.current && !window.confirm('You have unsaved changes. Discard them?')) return
      dirty.current = false
      router.replace(next ? `/notes?id=${next}` : '/notes', { scroll: false })
    },
    [router],
  )

  const createFromLink = useMutation({
    mutationFn: (title: string) => post<Note>('/api/notes', { title, body: '', tags: [], project_id: null, pinned: false } satisfies NoteInput),
    onSuccess: (n) => {
      toast(`Created “${n.title}”.`)
      qc.invalidateQueries({ queryKey: ['notes'] })
      go(n.id)
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })

  const openTitle = useCallback(
    (title: string) => {
      const hit = all.data?.items.find((n) => n.title.trim().toLowerCase() === title.trim().toLowerCase())
      if (hit) go(hit.id)
      else if (!createFromLink.isPending) createFromLink.mutate(title)
    },
    [all.data, go, createFromLink],
  )
  const resolves = useCallback((title: string) => !!all.data?.items.some((n) => n.title.trim().toLowerCase() === title.trim().toLowerCase()), [all.data])

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Notes"
        description="Your own writing, in Markdown. Link notes with [[Note title]]. Threadline reads notes to find people, projects and tasks, but never edits your text."
        actions={
          <Button variant="primary" onClick={() => go('new')}>
            <Plus className="h-3.5 w-3.5" /> New note
          </Button>
        }
      />
      <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="self-start">
          <div className="space-y-2 border-b border-line p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search notes" aria-label="Search notes" className="h-8 pl-8 text-xs" />
            </div>
            {allTags.length > 0 && (
              <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by tag">
                {allTags.map((t) => (
                  <button key={t} aria-pressed={tag === t} onClick={() => setTag(tag === t ? '' : t)} className={cn('rounded px-1.5 py-0.5 text-[11px]', tag === t ? 'bg-accent-wash text-accent' : 'bg-sunken text-ink-2 hover:text-ink')}>
                    #{t}
                  </button>
                ))}
              </div>
            )}
          </div>
          {list.isLoading ? (
            <LoadingRows rows={5} />
          ) : list.error ? (
            <ErrorState error={list.error} retry={() => list.refetch()} />
          ) : !list.data || list.data.items.length === 0 ? (
            <EmptyState icon={<NotebookPen className="h-4 w-4" />} title={dq || tag ? 'No notes match' : 'No notes yet'} description={dq || tag ? 'Try another search or tag.' : 'Write your first note.'} action={!dq && !tag ? <Button size="sm" onClick={() => go('new')}>New note</Button> : undefined} />
          ) : (
            <ul className="scrollbar-thin max-h-[70vh] divide-y divide-line overflow-y-auto" aria-label="Notes">
              {list.data.items.map((n) => (
                <li key={n.id}>
                  <button onClick={() => go(n.id)} aria-current={n.id === id ? 'true' : undefined} className={cn('block w-full px-3 py-2.5 text-left hover:bg-surface-2', n.id === id && 'bg-accent-wash hover:bg-accent-wash')}>
                    <span className="flex items-center gap-1.5">
                      {n.pinned && <Pin className="h-3 w-3 shrink-0 text-accent" aria-label="Pinned" />}
                      <span className="truncate text-sm font-medium text-ink">{n.title}</span>
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-ink-3">{n.body.replace(/^#.*$/m, '').replace(/^[\s>*#-]+(\[[ x]\]\s*)?/gm, '').replace(/[*`]|\[\[|\]\]/g, '').trim().slice(0, 90) || 'Empty note'}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-ink-3">
                      {relDays(n.updated_at, now)}
                      {n.tags.slice(0, 3).map((t) => (
                        <span key={t} className="rounded bg-sunken px-1">
                          #{t}
                        </span>
                      ))}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="min-w-0">
          {!id ? (
            <Card>
              <EmptyState icon={<NotebookPen className="h-4 w-4" />} title="Select a note or start a new one" description="Notes are processed like any other source: people, projects and tasks they mention show up as AI annotations next to your text." action={<Button onClick={() => go('new')}>New note</Button>} />
            </Card>
          ) : id === 'new' ? (
            <Editor key="new" note={null} projects={projects.data?.items ?? []} onOpenTitle={openTitle} resolves={resolves} dirtyRef={dirty} onSaved={(nid) => go(nid)} onDeleted={() => go(null)} />
          ) : note.isLoading ? (
            <Card>
              <LoadingRows rows={8} />
            </Card>
          ) : note.error || !note.data ? (
            <Card>
              <ErrorState error={note.error} retry={() => note.refetch()} />
            </Card>
          ) : (
            <Editor key={note.data.id} note={note.data} projects={projects.data?.items ?? []} onOpenTitle={openTitle} resolves={resolves} dirtyRef={dirty} onSaved={() => {}} onDeleted={() => go(null)} />
          )}
        </div>
      </div>
    </div>
  )
}

type Mode = 'write' | 'preview'

function Editor({
  note,
  projects,
  onOpenTitle,
  resolves,
  dirtyRef,
  onSaved,
  onDeleted,
}: {
  note: NoteDetail | null
  projects: ProjectSummary[]
  onOpenTitle: (t: string) => void
  resolves: (t: string) => boolean
  dirtyRef: { current: boolean }
  onSaved: (id: string) => void
  onDeleted: () => void
}) {
  const qc = useQueryClient()
  const toast = useToast()
  const [title, setTitle] = useState(note?.title ?? '')
  const [body, setBody] = useState(note?.body ?? '')
  const [tags, setTags] = useState((note?.tags ?? []).join(', '))
  const [projectId, setProjectId] = useState(note?.project?.id ?? '')
  const [pinned, setPinned] = useState(note?.pinned ?? false)
  const [mode, setMode] = useState<Mode>(note ? 'preview' : 'write')
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Server-side processing can add hashtags/project to the note; adopt them when the note refetches.
  const serverTags = (note?.tags ?? []).join(', ')
  const serverProject = note?.project?.id ?? ''
  const baseline = useRef({ title: note?.title ?? '', body: note?.body ?? '', tags: serverTags, projectId: serverProject, pinned: note?.pinned ?? false })
  useEffect(() => {
    const b = baseline.current
    if (tags === b.tags && serverTags !== b.tags) setTags(serverTags)
    if (projectId === b.projectId && serverProject !== b.projectId) setProjectId(serverProject)
    baseline.current = { ...b, tags: serverTags, projectId: serverProject }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverTags, serverProject])

  const parsedTags = useMemo(() => Array.from(new Set(tags.split(',').map((t) => t.trim().replace(/^#/, '').toLowerCase()).filter(Boolean))), [tags])
  const b = baseline.current
  const dirty = !note || title !== b.title || body !== b.body || parsedTags.join(',') !== b.tags.split(',').map((t) => t.trim()).filter(Boolean).join(',') || projectId !== b.projectId || pinned !== b.pinned
  const hasContent = title.trim().length > 0 || body.trim().length > 0
  useEffect(() => {
    dirtyRef.current = note ? dirty : hasContent
  }, [dirty, hasContent, note, dirtyRef])
  useEffect(() => () => void (dirtyRef.current = false), [dirtyRef])

  const save = useMutation({
    mutationFn: () => {
      const payload: NoteInput = { title: title.trim(), body, tags: parsedTags, project_id: projectId || null, pinned }
      return note ? put<Note>(`/api/notes/${note.id}`, payload) : post<Note>('/api/notes', payload)
    },
    onSuccess: (saved) => {
      baseline.current = { title: saved.title, body: saved.body, tags: saved.tags.join(', '), projectId: saved.project?.id ?? '', pinned: saved.pinned }
      setTags(saved.tags.join(', '))
      setProjectId(saved.project?.id ?? '')
      dirtyRef.current = false
      toast(note ? 'Note saved.' : 'Note created.')
      qc.invalidateQueries({ queryKey: ['notes'] })
      qc.invalidateQueries({ queryKey: ['note', saved.id] })
      qc.invalidateQueries({ queryKey: ['inferences'] })
      qc.invalidateQueries({ queryKey: ['timeline'] })
      // annotations are produced by background processing; look again shortly
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['note', saved.id] })
        qc.invalidateQueries({ queryKey: ['inferences'] })
      }, 2000)
      if (!note) onSaved(saved.id)
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })

  const remove = useMutation({
    mutationFn: () => del(`/api/notes/${note!.id}`),
    onSuccess: () => {
      dirtyRef.current = false
      toast('Note deleted.')
      qc.invalidateQueries({ queryKey: ['notes'] })
      qc.removeQueries({ queryKey: ['note', note!.id] })
      onDeleted()
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })

  const canSave = title.trim().length > 0 && dirty && !save.isPending
  const saveRef = useRef(() => {})
  useEffect(() => {
    saveRef.current = () => canSave && save.mutate()
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        saveRef.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const links = useMemo(() => wikiLinks(body), [body])

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
      <Card className="min-w-0">
        <div className="space-y-3 border-b border-line p-4">
          <div className="flex items-start gap-2">
            <label htmlFor="note-title" className="sr-only">
              Title
            </label>
            <input
              id="note-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Untitled note"
              maxLength={300}
              className="min-w-0 flex-1 bg-transparent font-serif text-xl font-medium text-ink placeholder:text-ink-3 focus:outline-none"
            />
            <Button size="icon" variant="ghost" aria-pressed={pinned} aria-label={pinned ? 'Unpin note' : 'Pin note'} title={pinned ? 'Unpin' : 'Pin to top'} onClick={() => setPinned((p) => !p)}>
              <Pin className={cn('h-4 w-4', pinned ? 'fill-current text-accent' : 'text-ink-3')} />
            </Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="note-tags" hint="comma-separated; #hashtags in the text are added too">
                Tags
              </Label>
              <Input id="note-tags" className="h-8 text-xs" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="atlas, risks" />
            </div>
            <div>
              <Label htmlFor="note-project">Project</Label>
              <Select id="note-project" className="h-8 w-full text-xs" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">No project (AI may suggest)</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Tabs<Mode>
              className="border-none"
              value={mode}
              onChange={setMode}
              tabs={[
                { value: 'write', label: 'Write' },
                { value: 'preview', label: 'Preview' },
              ]}
            />
            <div className="flex items-center gap-2">
              <span className="hidden text-[11px] text-ink-3 sm:inline">
                {dirty && note ? 'Unsaved changes · ' : ''}
                <Kbd>⌘</Kbd> <Kbd>S</Kbd>
              </span>
              {note && (
                <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(true)} aria-label="Delete note">
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
              <Button size="sm" variant="primary" disabled={!canSave} loading={save.isPending} onClick={() => save.mutate()}>
                <Save className="h-3.5 w-3.5" /> {note ? 'Save' : 'Create'}
              </Button>
            </div>
          </div>
        </div>
        {mode === 'write' ? (
          <div className="p-4">
            <label htmlFor="note-body" className="sr-only">
              Note body (Markdown)
            </label>
            <Textarea
              id="note-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={20}
              placeholder={'# Heading\n\nWrite in Markdown. Link another note with [[Its title]].\n\n- [ ] Lines like this become suggested tasks'}
              className="min-h-[420px] resize-y font-mono text-[13px] leading-relaxed"
            />
          </div>
        ) : (
          <div className="min-h-[420px] px-5 py-4">{body.trim() ? <NoteMarkdown body={body} onOpenLink={onOpenTitle} resolves={resolves} /> : <p className="text-sm text-ink-3">Nothing written yet.</p>}</div>
        )}
      </Card>

      <div className="min-w-0 space-y-5">
        {note ? <Annotations note={note} /> : <Card className="p-4 text-xs text-ink-3">AI annotations appear here after you save.</Card>}
        <Card>
          <CardHeader title="Links" description="Write [[Note title]] to link notes." />
          <div className="space-y-3 px-4 py-3 text-xs">
            <div>
              <div className="mb-1 font-medium text-ink-2">Links to</div>
              {links.length === 0 ? (
                <p className="text-ink-3">No outgoing links.</p>
              ) : (
                <ul className="space-y-1">
                  {links.map((t) => (
                    <li key={t}>
                      <button className={cn('inline-flex items-center gap-1 text-left hover:underline', resolves(t) ? 'text-accent' : 'text-ink-3')} onClick={() => onOpenTitle(t)}>
                        <Link2 className="h-3 w-3" aria-hidden /> {t}
                        {!resolves(t) && <span className="text-[10px]">(create)</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div className="mb-1 font-medium text-ink-2">Linked from</div>
              {!note || note.backlinks.length === 0 ? (
                <p className="text-ink-3">No notes link here yet.</p>
              ) : (
                <ul className="space-y-1">
                  {note.backlinks.map((bl) => (
                    <li key={bl.id}>
                      <Link href={`/notes?id=${bl.id}`} className="inline-flex items-center gap-1 text-accent hover:underline">
                        <Link2 className="h-3 w-3" aria-hidden /> {bl.title || 'Untitled'}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      </div>

      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete this note?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-2">“{note?.title}” and everything Threadline derived from it (suggested tasks, commitments, links) will be removed.</p>
      </Dialog>
    </div>
  )
}

function Annotations({ note }: { note: NoteDetail }) {
  const qc = useQueryClient()
  const toast = useToast()
  const inferences = useQuery({ queryKey: ['inferences', 'pending'], queryFn: () => get<{ items: InferenceItem[] }>('/api/inferences?status=pending') })
  const pending = inferences.data?.items.find((i) => i.subject_type === 'note' && i.subject_id === note.id && i.kind === 'project_association')
  const decide = useMutation({
    mutationFn: ({ iid, action }: { iid: string; action: 'confirm' | 'reject' }) => post(`/api/inferences/${iid}`, { action }),
    onSuccess: (_r, v) => {
      toast(v.action === 'confirm' ? 'Project confirmed for this note.' : 'Suggestion rejected. The note has no project now.')
      qc.invalidateQueries({ queryKey: ['inferences'] })
      qc.invalidateQueries({ queryKey: ['note', note.id] })
      qc.invalidateQueries({ queryKey: ['notes'] })
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })

  const seen = new Set<string>()
  const anns = note.ai_annotations.filter((a) => {
    const k = `${a.type}:${a.ref_id ?? a.text}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
  const people = anns.filter((a) => a.type === 'person')
  const projects = anns.filter((a) => a.type === 'project')
  const tasks = anns.filter((a) => a.type === 'task')
  const other = anns.filter((a) => !['person', 'project', 'task'].includes(a.type))

  return (
    <Card className="border-uncertain/25">
      <CardHeader title={<AiLabel>Detected by AI</AiLabel>} description="Stored separately. Your text above is never modified by AI." />
      {anns.length === 0 ? (
        <p className="px-4 py-3 text-xs text-ink-3">Nothing detected in this note yet.</p>
      ) : (
        <div className="space-y-3 px-4 py-3 text-xs">
          {people.length > 0 && (
            <section>
              <h3 className="mb-1 font-medium text-ink-2">People</h3>
              <ul className="space-y-1">
                {people.map((a) => (
                  <li key={`${a.ref_id}-${a.text}`} className="flex items-center justify-between gap-2">
                    {a.ref_id ? (
                      <Link href={`/people/${a.ref_id}`} className="inline-flex min-w-0 items-center gap-1.5 text-ink hover:text-accent">
                        <Avatar name={a.text} className="h-5 w-5 text-[9px]" />
                        <span className="truncate">“{a.text}”</span>
                      </Link>
                    ) : (
                      <span className="text-ink">“{a.text}”</span>
                    )}
                    <Confidence value={a.confidence} />
                  </li>
                ))}
              </ul>
            </section>
          )}
          {projects.length > 0 && (
            <section>
              <h3 className="mb-1 font-medium text-ink-2">Project</h3>
              {pending ? (
                <InferenceCard
                  label="Suggested project"
                  value={pending.value_label ?? '—'}
                  confidence={pending.confidence}
                  reasons={pending.reasons}
                  busy={decide.isPending}
                  onConfirm={() => decide.mutate({ iid: pending.id, action: 'confirm' })}
                  onIgnore={() => decide.mutate({ iid: pending.id, action: 'reject' })}
                />
              ) : (
                <ul className="space-y-1.5">
                  {projects.map((a) => (
                    <li key={`${a.ref_id}-${a.text}`}>
                      <div className="flex items-center justify-between gap-2">
                        {a.ref_id ? <ProjectChip project={{ id: a.ref_id, name: a.text ?? 'Project', color: null }} /> : <span>{a.text}</span>}
                        <span className="flex items-center gap-1.5">
                          {a.status && <Badge tone={a.status === 'pending' ? 'uncertain' : a.status === 'rejected' ? 'neutral' : 'success'}>{a.status}</Badge>}
                          <Confidence value={a.confidence} />
                        </span>
                      </div>
                      {a.reasons && a.reasons.length > 0 && <p className="mt-0.5 text-ink-3">{a.reasons.join(' · ')}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
          {tasks.length > 0 && (
            <section>
              <h3 className="mb-1 font-medium text-ink-2">Suggested tasks</h3>
              <ul className="space-y-1">
                {tasks.map((a) => (
                  <li key={a.text} className="flex items-start justify-between gap-2">
                    <span className="text-ink">{a.text}</span>
                    <Confidence value={a.confidence} />
                  </li>
                ))}
              </ul>
              <Link href="/tasks?view=suggested" className="mt-1 inline-block text-accent hover:underline">
                Review suggested tasks
              </Link>
            </section>
          )}
          {other.length > 0 && (
            <section>
              <h3 className="mb-1 font-medium text-ink-2">Other</h3>
              <ul className="space-y-1">
                {other.map((a, i) => (
                  <li key={i} className="flex items-center justify-between gap-2">
                    <span>
                      <Badge tone="neutral">{a.type}</Badge> {a.text}
                    </span>
                    <Confidence value={a.confidence} />
                  </li>
                ))}
              </ul>
            </section>
          )}
          <p className="border-t border-line pt-2 text-[11px] text-ink-3">
            Wrong? Edit the note and save; annotations are recomputed from your text.
          </p>
        </div>
      )}
    </Card>
  )
}
