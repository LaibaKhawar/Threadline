// Response shapes for the Work-area endpoints (threads, briefs, projects, commitment detail, inferences).
import type { CalendarEvent, Commitment, Decision, DocumentItem, Email, Note, ProjectBrief, ProjectSummary, Task } from '@/lib/types'

export type ThreadSummary = {
  id: string
  subject: string
  message_count: number
  first_at: string | null
  last_at: string | null
  project: ProjectBrief | null
  awaiting: 'me' | 'them' | null
  commitments: number
  last: Email | null
  importance: number
}

export type ThreadInference = {
  id: string
  subject_id: string
  value_label: string | null
  value_id: string | null
  confidence: number
  reasons: string[]
  status: 'pending' | 'confirmed' | 'changed' | 'rejected' | string
}

export type ThreadDetail = {
  id: string
  subject: string
  project: ProjectBrief | null
  awaiting: 'me' | 'them' | null
  emails: (Email & { body: string | null })[]
  commitments: Commitment[]
  decisions: Decision[]
  tasks: Task[]
  inferences: ThreadInference[]
}

export type InferenceAction = { action: 'confirm' | 'change' | 'reject'; project_id?: string; apply_to_thread?: boolean }

export type EventDetail = CalendarEvent & { commitments: Commitment[]; decisions: Decision[] }

export type BriefEvidence = { source_type: string; source_id: string; span?: string | null; label?: string | null }
export type BriefCommitment = {
  ref: { type: string; id: string }
  title: string
  status: string
  kind: string
  actor: string | null
  recipient: string | null
  due_at: string | null
  confidence: number
  reason: string | null
  evidence: BriefEvidence[]
}

export type MeetingBrief = {
  event: { ref: { type: string; id: string }; title: string; start_at: string; end_at: string; description: string | null; location: string | null }
  participants: { ref: { type: string; id: string }; name: string; title: string | null; organization: string | null; last_interaction_at: string | null }[]
  project: { project: string; ref: { type: string; id: string }; status: string; label: string; signals: { signal: string; weight: number }[] } | null
  recent_emails: { ref: { type: string; id: string }; subject: string; from: string; sent_at: string; snippet: string }[]
  open_commitments: BriefCommitment[]
  decisions: { ref: { type: string; id: string }; topic: string; chosen: string; rejected: string[]; status: string; decided_at: string; evidence: BriefEvidence[] }[]
  related_documents: { ref: { type: string; id: string }; title: string; authored_at: string | null; retrieved?: boolean }[]
  previous_meeting: { ref: { type: string; id: string }; title: string; start_at: string; notes: string | null } | null
  generated_at: string
  note: string
}

export type ProjectFact = {
  attribute: string
  value: string
  content: string
  status: string
  valid_from: string | null
  valid_to: string | null
  source: { type: string | null; id: string | null; span: string | null }
}

export type ProjectTimelineItem = { occurred_at: string; kind: string; title: string; ref: { type: string | null; id: string | null } }

/** Note: the detail endpoint replaces the summary's `decisions` count with the full list. */
export type ProjectDetail = Omit<ProjectSummary, 'decisions'> & {
  tasks: Task[]
  commitments: Commitment[]
  decisions: Decision[]
  emails: Email[]
  meetings: CalendarEvent[]
  documents: DocumentItem[]
  notes: Note[]
  facts: ProjectFact[]
  timeline: ProjectTimelineItem[]
}

export type CommitmentEvidence = {
  role: 'source' | 'reaffirmed' | 'fulfillment' | 'change' | string
  source_type: string
  source_id: string
  span: string | null
  observed_at: string | null
  confidence: number | null
  location: Record<string, unknown> | null
}

export type FulfillmentCandidate = {
  id: string
  source_type: string
  source_id: string
  score: number
  signals: Record<string, unknown>
  outcome: 'candidate' | 'fulfilled' | 'rejected' | 'cancelled' | string
}

export type CommitmentDetail = Commitment & {
  evidence: CommitmentEvidence[]
  due_history: { old_due_at: string | null; new_due_at: string | null; source_type: string; source_id: string; span: string | null; observed_at: string | null }[]
  candidates: FulfillmentCandidate[]
  dependencies: ({ depends_on: string } | { required_by: string })[]
}

export type CommitmentList = { now: string; counts: Record<string, number>; items: Commitment[] }
export type TaskList = { now: string; auto_create: boolean; items: Task[] }

export type PersonListItem = {
  id: string
  name: string
  email: string | null
  title: string | null
  organization: string | null
  is_self: boolean
  last_interaction_at: string | null
  open_items: number
  emails_sent: number
}
