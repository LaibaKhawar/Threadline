'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowUp, Check, ChevronDown, ChevronRight, CircleDashed, MessageSquarePlus, Pencil, ShieldCheck, ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { type KeyboardEvent, type ReactNode, Suspense, useEffect, useRef, useState } from 'react'

import { useSource } from '@/components/source-drawer'
import { useToast } from '@/components/toast'
import { AgentIcon, SOURCE_ICON } from '@/components/ui/ai'
import { Badge, Button, Card, Dialog, EmptyState, Input, Label, PageHeader, Select, Switch, Textarea } from '@/components/ui/primitives'
import { del, errorMessage, get, post } from '@/lib/api'
import type { AgentStep, AskResponse, Citation, Proposal, ProjectSummary } from '@/lib/types'
import { cn } from '@/lib/utils'

const EXAMPLES = [
  'What am I waiting on Ahmed for?',
  'What promises did I make this week?',
  'What projects need my attention?',
  'When did we decide to use PostgreSQL?',
  'What changed about Project Atlas in September?',
  'Show everything related to Sarah and Project Phoenix',
  'Which tasks are blocked?',
  'Which people haven’t replied to me?',
  'Prepare me for my 11 AM meeting',
  'What was the Atlas launch deadline before it was moved?',
  'What company did Sarah work for in March?',
  'What decisions have been superseded?',
]

type Turn = AskResponse & { question: string; created_at?: string; feedback?: string | null }
type ConversationList = { items: { id: string; title: string; updated_at: string }[] }
type ConversationDetail = { id: string; title: string; runs: (Omit<AskResponse, 'parsed' | 'model'> & { question: string; feedback: string | null; created_at: string; model: string | null })[] }

function AssistantInner() {
  const params = useSearchParams()
  const qc = useQueryClient()
  const toast = useToast()
  const [conversationId, setConversationId] = useState<string | null>(params.get('c'))
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState(params.get('q') ?? '')
  const [useLlm, setUseLlm] = useState(true)
  const [projectId, setProjectId] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const conversations = useQuery({ queryKey: ['conversations'], queryFn: () => get<ConversationList>('/api/conversations') })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => get<{ items: ProjectSummary[] }>('/api/projects') })

  const loadConversation = async (id: string) => {
    const c = await get<ConversationDetail>(`/api/conversations/${id}`)
    setConversationId(id)
    setTurns(c.runs.map((r) => ({ ...r, parsed: {}, model: r.model ?? null })))
  }
  useEffect(() => {
    const c = params.get('c')
    if (c) void loadConversation(c)
  }, [params])

  const ask = useMutation({
    mutationFn: (question: string) => {
      const project = projects.data?.items.find((p) => p.id === projectId)
      const q = project && !question.toLowerCase().includes(project.name.toLowerCase()) ? `${question} (Project ${project.name})` : question
      return post<AskResponse>('/api/assistant/ask', { question: q, conversation_id: conversationId, use_llm: useLlm })
    },
    onSuccess: (r, question) => {
      setTurns((t) => [...t, { ...r, question }])
      setConversationId(r.conversation_id)
      qc.invalidateQueries({ queryKey: ['conversations'] })
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, ask.isPending])

  const send = (q?: string) => {
    const text = (q ?? input).trim()
    if (!text || ask.isPending) return
    setInput('')
    ask.mutate(text)
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }
  const newChat = () => {
    setConversationId(null)
    setTurns([])
  }
  const removeConversation = async (id: string) => {
    await del(`/api/conversations/${id}`)
    if (id === conversationId) newChat()
    qc.invalidateQueries({ queryKey: ['conversations'] })
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
      <aside className="hidden lg:block" aria-label="Conversation history">
        <Button className="mb-3 w-full" onClick={newChat}>
          <MessageSquarePlus className="h-4 w-4" /> New conversation
        </Button>
        <ul className="space-y-0.5">
          {conversations.data?.items.map((c) => (
            <li key={c.id} className="group flex items-center">
              <button
                onClick={() => loadConversation(c.id)}
                className={cn('min-w-0 flex-1 truncate rounded px-2 py-1.5 text-left text-xs', c.id === conversationId ? 'bg-surface font-medium text-ink shadow-card' : 'text-ink-2 hover:bg-sunken')}
              >
                {c.title}
              </button>
              <button aria-label={`Delete conversation ${c.title}`} className="ml-1 rounded p-1 text-ink-3 opacity-0 hover:text-danger group-hover:opacity-100 focus:opacity-100" onClick={() => removeConversation(c.id)}>
                <Trash2 className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="min-w-0">
        <PageHeader
          title="Assistant"
          description="Answers come only from your own data, with numbered sources. It reads; it never sends, deletes or changes anything without your approval."
        />
        <div className="space-y-6 pb-44">
          {turns.length === 0 && !ask.isPending && (
            <Card className="p-5">
              <p className="mb-3 text-sm text-ink-2">Try one of these:</p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLES.map((e) => (
                  <button key={e} onClick={() => send(e)} className="rounded-full border border-line bg-surface-2 px-3 py-1 text-xs text-ink-2 hover:border-accent hover:text-accent">
                    {e}
                  </button>
                ))}
              </div>
            </Card>
          )}
          {turns.map((t) => (
            <TurnView key={t.run_id} turn={t} />
          ))}
          {ask.isPending && (
            <div className="flex items-center gap-3 text-sm text-ink-3" role="status">
              <AgentIcon />
              <span className="inline-flex items-center gap-2">
                <CircleDashed className="h-4 w-4 animate-spin" /> Planning, searching your memory and verifying citations…
              </span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-line bg-bg/95 backdrop-blur md:left-56">
          <div className="mx-auto max-w-[1000px] px-4 py-3 sm:px-8">
            <div className="flex items-end gap-2 rounded-lg border border-line bg-surface p-2 shadow-card focus-within:border-accent">
              <Textarea
                aria-label="Ask a question"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKey}
                rows={2}
                placeholder="Ask about your emails, meetings, documents, commitments…"
                className="resize-none border-0 bg-transparent focus:border-0"
              />
              <Button variant="primary" size="icon" aria-label="Send" onClick={() => send()} disabled={!input.trim()} loading={ask.isPending}>
                {!ask.isPending && <ArrowUp className="h-4 w-4" />}
              </Button>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-ink-3">
              <div className="w-56">
                <Switch checked={useLlm} onChange={setUseLlm} label="Use language model" />
              </div>
              <label className="flex items-center gap-2">
                <span>Project context</span>
                <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label="Project context" className="h-7 text-xs">
                  <option value="">Any</option>
                  {projects.data?.items.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
              </label>
              <span className="inline-flex items-center gap-1">
                <ShieldCheck className="h-3 w-3" /> Retrieved content is treated as data, never as instructions.
              </span>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

/** Render answer text, turning [S3] markers into clickable citation buttons. */
function AnswerText({ text, citations }: { text: string; citations: Citation[] }) {
  const { open } = useSource()
  const byId = new Map(citations.map((c) => [c.id, c]))
  const lines = text.split('\n')
  return (
    <div className="space-y-1.5 text-[15px] leading-relaxed text-ink">
      {lines.map((line, li) => {
        const bullet = /^\s*[-*•]\s+/.test(line)
        const parts: ReactNode[] = []
        const re = /\[S(\d+)\]/g
        let last = 0
        let m: RegExpExecArray | null
        const body = bullet ? line.replace(/^\s*[-*•]\s+/, '') : line
        while ((m = re.exec(body))) {
          parts.push(body.slice(last, m.index))
          const c = byId.get(`S${m[1]}`)
          parts.push(
            c ? (
              <button
                key={`${li}-${m.index}`}
                onClick={() => open({ type: c.source_type, id: c.source_id, span: c.text })}
                className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-accent-wash px-1 align-[1px] text-[10px] font-semibold text-accent hover:bg-accent hover:text-accent-ink"
                aria-label={`Source ${m[1]}: ${c.title}`}
                title={c.title}
              >
                {m[1]}
              </button>
            ) : (
              <sup key={`${li}-${m.index}`}>[{m[1]}]</sup>
            ),
          )
          last = m.index + m[0].length
        }
        parts.push(body.slice(last))
        return bullet ? (
          <div key={li} className="flex gap-2 pl-1">
            <span className="text-ink-3">•</span>
            <p>{parts}</p>
          </div>
        ) : (
          <p key={li}>{parts}</p>
        )
      })}
    </div>
  )
}

function TurnView({ turn }: { turn: Turn }) {
  const { open } = useSource()
  const [showSteps, setShowSteps] = useState(false)
  const [feedback, setFeedback] = useState(turn.feedback ?? null)
  const v = turn.verification as { cited_sentences?: number; removed_unsupported?: number; invalid_citations?: number; date_mismatches?: number; flagged_sentences?: string[] }
  const sendFeedback = async (f: string) => {
    await post(`/api/runs/${turn.run_id}/feedback`, { feedback: f })
    setFeedback(f)
  }
  const modeLabel = turn.answer_mode === 'llm' ? `Local model${turn.model ? ` · ${turn.model}` : ''}` : turn.answer_mode === 'extractive' ? 'Extractive (no model)' : 'Policy'
  return (
    <article className="animate-fade-in space-y-3">
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-lg bg-sunken px-3.5 py-2 text-sm text-ink">{turn.question}</p>
      </div>
      <div className="flex gap-3">
        <AgentIcon />
        <div className="min-w-0 flex-1 space-y-3">
          <AnswerText text={turn.answer} citations={turn.citations} />
          {!!v?.flagged_sentences?.length && (
            <div className="flex gap-2 rounded-md border border-warning/30 bg-warning-wash p-2.5 text-xs text-ink-2" role="note">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
              <div>
                <p className="font-medium text-warning">Check these: a date in them wasn’t found in the cited source.</p>
                <ul className="mt-1 list-disc pl-4">
                  {v.flagged_sentences.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {turn.proposals?.map((p) => <ProposalCard key={p.id} proposal={p} />)}
          {turn.citations.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">Sources</div>
              <ol className="grid gap-1.5 sm:grid-cols-2">
                {turn.citations.map((c) => (
                  <li key={c.id}>
                    <button onClick={() => open({ type: c.source_type, id: c.source_id, span: c.text })} className="flex w-full gap-2 rounded-md border border-line bg-surface p-2 text-left hover:border-accent">
                      <span className="mt-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-accent-wash px-1 text-[10px] font-semibold text-accent">{c.id.slice(1)}</span>
                      <span className="min-w-0">
                        <span className="flex items-center gap-1 text-xs font-medium text-ink">
                          {SOURCE_ICON[c.source_type]}
                          <span className="truncate">{c.title}</span>
                        </span>
                        <span className="line-clamp-2 text-[11px] text-ink-3">{c.text}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-3">
            <Badge tone={turn.answer_mode === 'llm' ? 'accent' : 'neutral'}>{modeLabel}</Badge>
            {turn.latency_ms !== null && <span>{(turn.latency_ms / 1000).toFixed(1)}s</span>}
            {v && (
              <span title="The verifier checks every sentence for valid citations; uncited factual sentences are removed.">
                {v.cited_sentences ?? 0} cited · {v.removed_unsupported ?? 0} unsupported removed{v.invalid_citations ? ` · ${v.invalid_citations} invalid citations dropped` : ''}
              </span>
            )}
            <button onClick={() => setShowSteps((s) => !s)} className="inline-flex items-center gap-0.5 text-ink-2 hover:text-accent" aria-expanded={showSteps}>
              {showSteps ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />} Activity
            </button>
            <span className="ml-auto inline-flex gap-0.5">
              <Button size="icon" variant="ghost" aria-label="Helpful" className={cn(feedback === 'helpful' && 'text-success')} onClick={() => sendFeedback('helpful')}>
                <ThumbsUp className="h-3.5 w-3.5" />
              </Button>
              <Button size="icon" variant="ghost" aria-label="Not helpful" className={cn(feedback === 'not_helpful' && 'text-danger')} onClick={() => sendFeedback('not_helpful')}>
                <ThumbsDown className="h-3.5 w-3.5" />
              </Button>
            </span>
          </div>
          {showSteps && <Steps steps={turn.steps} />}
        </div>
      </div>
    </article>
  )
}

const PHASE_TONE: Record<string, 'accent' | 'info' | 'neutral' | 'warning' | 'success' | 'uncertain'> = {
  plan: 'uncertain',
  execute: 'info',
  observe: 'neutral',
  revise: 'warning',
  verify: 'accent',
  answer: 'success',
}

function Steps({ steps }: { steps: AgentStep[] }) {
  return (
    <Card className="p-3">
      <p className="mb-2 text-[11px] text-ink-3">Structured activity log (actions taken, not hidden reasoning).</p>
      <ol className="space-y-1.5">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-2 text-xs">
            <Badge tone={PHASE_TONE[s.phase] ?? 'neutral'} className="w-16 justify-center uppercase">
              {s.phase}
            </Badge>
            <span className="text-ink-2">{s.summary}</span>
          </li>
        ))}
      </ol>
    </Card>
  )
}

function ProposalCard({ proposal }: { proposal: Proposal }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [state, setState] = useState(proposal)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ to: String(proposal.payload.to ?? ''), subject: String(proposal.payload.subject ?? ''), body: String(proposal.payload.body ?? '') })
  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject') => post<Proposal>(`/api/proposals/${proposal.id}`, { decision, payload: editing || decision === 'approve' ? draft : undefined }),
    onSuccess: (p) => {
      setState(p)
      setEditing(false)
      qc.invalidateQueries({ queryKey: ['proposals'] })
      toast(p.status === 'rejected' ? 'Proposal rejected' : String(p.result?.message ?? 'Approved'))
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const p = state.payload
  return (
    <Card className="border-uncertain/30">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          Proposed action: {state.tool === 'draft_email' ? `follow-up email to ${String(p.to_name ?? p.to ?? '')}` : state.tool}
        </div>
        <div className="flex items-center gap-1.5">
          {state.permission && (
            <Badge tone="warning" title="Tool permission">
              {state.permission.access.toUpperCase()} · {state.permission.scope} · approval required
            </Badge>
          )}
          <Badge tone={state.status === 'pending' ? 'uncertain' : state.status === 'rejected' ? 'neutral' : 'success'}>{state.status}</Badge>
        </div>
      </div>
      <div className="space-y-2 p-3 text-sm">
        <p className="text-xs text-ink-3">Why: {state.reason}</p>
        <dl className="grid grid-cols-[64px_1fr] gap-x-2 gap-y-1 text-xs">
          <dt className="text-ink-3">To</dt>
          <dd>{String(p.to ?? '')}</dd>
          <dt className="text-ink-3">Subject</dt>
          <dd>{String(p.subject ?? '')}</dd>
        </dl>
        <pre className="whitespace-pre-wrap rounded-md bg-sunken p-2.5 font-sans text-xs text-ink-2">{String(p.body ?? '')}</pre>
        {typeof p.note === 'string' && <p className="text-[11px] text-ink-3">{p.note}</p>}
        {state.status === 'pending' && (
          <div className="flex gap-2">
            <Button size="sm" variant="primary" onClick={() => decide.mutate('approve')} loading={decide.isPending}>
              <Check className="h-3 w-3" /> Approve
            </Button>
            <Button size="sm" onClick={() => setEditing(true)}>
              <Pencil className="h-3 w-3" /> Edit
            </Button>
            <Button size="sm" variant="ghost" onClick={() => decide.mutate('reject')}>
              <X className="h-3 w-3" /> Reject
            </Button>
          </div>
        )}
        {state.result?.message !== undefined && <p className="text-xs text-ink-2">{String(state.result.message)}</p>}
      </div>
      <Dialog
        open={editing}
        onClose={() => setEditing(false)}
        title="Edit draft"
        wide
        footer={
          <>
            <Button onClick={() => setEditing(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => decide.mutate('approve')} loading={decide.isPending}>
              Approve edited draft
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <Label htmlFor="d-to">To</Label>
            <Input id="d-to" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </div>
          <div>
            <Label htmlFor="d-subj">Subject</Label>
            <Input id="d-subj" value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
          </div>
          <div>
            <Label htmlFor="d-body">Body</Label>
            <Textarea id="d-body" rows={8} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
          </div>
        </div>
      </Dialog>
    </Card>
  )
}

export default function AssistantPage() {
  return (
    <Suspense fallback={<EmptyState title="Loading…" />}>
      <AssistantInner />
    </Suspense>
  )
}

