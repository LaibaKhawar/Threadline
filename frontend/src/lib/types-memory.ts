// Response shapes for the Memory-area pages (people, graph, timeline, documents, notes).
import type { CalendarEvent, Commitment, Decision, DocumentItem, Email, Note, PersonBrief, ProjectBrief, Task } from '@/lib/types'

export type EvidenceRef = { source_type: string | null; source_id: string | null; span: string | null }

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

export type MergeIdentity = { id: string; name: string; email: string | null; aliases: string[] }
export type MergeCandidate = { id: string; a: MergeIdentity | null; b: MergeIdentity | null; score: number; reasons: string[] }
export type PeopleResponse = { items: PersonListItem[]; merge_candidates: MergeCandidate[] }

export type Employment = {
  organization: string
  valid_from: string | null
  valid_to: string | null
  status: string
  confidence: number
  basis: string | null
  title: string | null
  evidence: EvidenceRef | null
}

export type Alias = { id: string; alias: string; kind: string }

export type TimelineRef = { type: string | null; id: string | null }

export type PersonDetail = {
  id: string
  name: string
  email: string | null
  title: string | null
  organization: string | null
  is_self: boolean
  notes: string | null
  created_by: string | null
  last_interaction_at: string | null
  aliases: Alias[]
  employment: Employment[]
  projects: ProjectBrief[]
  waiting_on_them: Commitment[]
  you_owe_them: Commitment[]
  emails: Email[]
  meetings: CalendarEvent[]
  commitments: Commitment[]
  decisions: Decision[]
  tasks: Task[]
  timeline: { occurred_at: string; kind: string; title: string; ref: TimelineRef }[]
}

export type PersonResponse = PersonDetail | { redirect: string }

// ----------------------------------------------------------------------------- graph

export type GraphNode = {
  id: string // "type:uuid"
  type: string
  ref_id: string
  label: string
  sent_at?: string
  start_at?: string
  created_at?: string
  decided_at?: string
  due_at?: string
  status?: string
}

export type GraphEdge = {
  id: string
  source: string
  target: string
  type: string
  status: string
  confidence: number
  valid_from: string | null
  valid_to: string | null
  observed_at: string | null
  evidence: EvidenceRef | null
  origin: string
  properties: Record<string, unknown>
}

export type GraphOverview = { nodes: GraphNode[]; edges: GraphEdge[]; edge_type_counts: Record<string, number> }
export type GraphNeighborhood = { center: string; nodes: GraphNode[]; edges: GraphEdge[] }
export type GraphSearch = { items: Pick<GraphNode, 'id' | 'type' | 'ref_id' | 'label'>[] }

// ----------------------------------------------------------------------------- timeline

export type TimelineEvent = {
  id: string
  occurred_at: string
  kind: string
  title: string
  detail: string | null
  ref: TimelineRef
  project: ProjectBrief | null
  future: boolean
}

// ----------------------------------------------------------------------------- documents

export type DocChunk = { id: string; ordinal: number; page: number | null; section: string | null; text: string }
export type DocumentDetail = DocumentItem & { text?: string; chunks: DocChunk[]; decisions: Decision[]; commitments: Commitment[] }
export type UploadResponse = { document: DocumentItem | null; duplicate: boolean }

// ----------------------------------------------------------------------------- notes

export type NoteDetail = Note & { backlinks: { id: string; title: string }[] }
export type NoteInput = { title: string; body: string; tags: string[]; project_id: string | null; pinned: boolean }

export type InferenceItem = {
  id: string
  kind: string
  subject_type: string
  subject_id: string
  subject_label: string | null
  value_id: string | null
  value_label: string | null
  confidence: number
  reasons: string[]
  status: string
}

export type { PersonBrief }
