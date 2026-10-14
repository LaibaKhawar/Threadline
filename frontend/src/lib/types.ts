export type Ref = { type: string | null; id: string | null }
export type PersonBrief = { id: string; name: string; email: string | null; is_self: boolean }
export type ProjectBrief = { id: string; name: string; color: string | null }

export type Evidence = { source_type: string; source_id: string; span?: string; label?: string | null; at?: string | null }

export type CommitmentStatus = 'OPEN' | 'FULFILLED' | 'OVERDUE' | 'CANCELLED' | 'UNCERTAIN' | 'REJECTED'

export type Commitment = {
  id: string
  kind: 'commitment' | 'request' | 'intention'
  description: string
  action: string
  object: string | null
  actor: PersonBrief | null
  actor_text: string | null
  recipient: PersonBrief | null
  status: CommitmentStatus
  confidence: number
  extractor: string
  due_at: string | null
  due_text: string | null
  detected_at: string
  project: ProjectBrief | null
  source: { type: string; id: string; span: string; start: number | null; end: number | null }
  resolution: { type: string | null; id: string | null; confidence: number | null; reason: string | null; resolved_at: string | null } | null
  user_confirmed: boolean
  user_modified: boolean
}

export type Decision = {
  id: string
  topic: string
  chosen: string
  rejected: string[]
  statement: string
  decided_at: string
  status: 'active' | 'superseded' | 'rejected'
  superseded_by_id: string | null
  project: ProjectBrief | null
  confidence: number
  source: { type: string; id: string; span: string }
  participants: PersonBrief[]
  user_confirmed: boolean
  reaffirmed?: { source_type: string; source_id: string; span: string; observed_at: string }[]
}

export type Task = {
  id: string
  title: string
  description: string | null
  project: ProjectBrief | null
  owner: PersonBrief | null
  status: 'suggested' | 'active' | 'blocked' | 'done' | 'dismissed'
  priority: 'low' | 'medium' | 'high' | 'urgent'
  due_at: string | null
  blocked_by: PersonBrief | null
  blocked_reason: string | null
  source: { type: string; id: string; span: string | null } | null
  confidence: number | null
  manually_created: boolean
  ai_suggested: boolean
  created_at: string
  completed_at: string | null
}

export type Email = {
  id: string
  thread_id: string | null
  subject: string
  from_addr: string
  from_name: string | null
  to: { name: string; email: string }[]
  cc: { name: string; email: string }[]
  sent_at: string
  direction: 'inbound' | 'outbound'
  attachments: { filename: string }[]
  project: ProjectBrief | null
  importance: number
  sender: PersonBrief | null
  snippet: string
  body?: string
}

export type CalendarEvent = {
  id: string
  title: string
  description: string | null
  location: string | null
  start_at: string
  end_at: string
  attendees: { name: string; email: string; response?: string }[]
  organizer: string | null
  notes: string | null
  project: ProjectBrief | null
  status: string
}

export type DocumentItem = {
  id: string
  title: string
  filename: string
  mime_type: string
  size_bytes: number
  page_count: number | null
  status: string
  error: string | null
  project: ProjectBrief | null
  author: PersonBrief | null
  authored_at: string | null
  created_at: string
  metadata: Record<string, unknown>
  text?: string
}

export type Note = {
  id: string
  title: string
  body: string
  tags: string[]
  ai_annotations: { type: string; text: string | null; ref_id?: string | null; confidence?: number; status?: string; reasons?: string[]; origin: string }[]
  project: ProjectBrief | null
  pinned: boolean
  created_at: string
  updated_at: string
}

export type HealthSignal = { signal: string; weight: number }
export type ProjectSummary = {
  id: string
  name: string
  description: string | null
  keywords: string[]
  color: string | null
  archived: boolean
  status_manual: string | null
  health: { status: string; label: string; score: number; signals: HealthSignal[] }
  open_tasks: number
  overdue_commitments: number
  decisions: number
  upcoming_meeting: { id: string; title: string; start_at: string } | null
  members: PersonBrief[]
}

export type Insight = {
  id: string
  kind: string
  title: string
  explanation: string
  evidence: Evidence[]
  confidence: number
  importance: number
  urgency: number
  score: number
  ref: Ref
  suggested_action: Record<string, unknown>
  feedback: string | null
  status: string
  created_at: string
}

export type Citation = { id: string; source_type: string; source_id: string; title: string; text: string; occurred_at: string | null; location: Record<string, unknown> }
export type AgentStep = { phase: string; summary: string; data: Record<string, unknown> }
export type Proposal = {
  id: string
  tool: string
  payload: Record<string, unknown>
  reason: string
  status: string
  result?: Record<string, unknown>
  permission?: { access: string; scope: string; sensitivity: string; requires_approval: boolean } | null
}
export type AskResponse = {
  run_id: string
  conversation_id: string | null
  answer: string
  answer_mode: string
  citations: Citation[]
  steps: AgentStep[]
  verification: Record<string, unknown> & { flagged_sentences?: string[] }
  parsed: Record<string, unknown>
  proposals: Proposal[]
  model: string | null
  latency_ms: number | null
}

export type SearchHit = {
  type: string
  id: string
  title: string
  snippet: string
  occurred_at: string | null
  project_id?: string | null
  location?: Record<string, unknown>
  channels: Record<string, number>
  score?: number
  status?: string
  source_type?: string
  source_id?: string
}
