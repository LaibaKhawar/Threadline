// Labels and tones for timeline kinds and graph node types (shared by timeline, people and graph pages).

export type Tone = 'neutral' | 'accent' | 'danger' | 'warning' | 'success' | 'info' | 'uncertain'

export const TIMELINE_KINDS: { value: string; label: string; tone: Tone }[] = [
  { value: 'decision', label: 'Decision', tone: 'accent' },
  { value: 'deadline_change', label: 'Deadline change', tone: 'warning' },
  { value: 'commitment', label: 'Commitment', tone: 'info' },
  { value: 'commitment_fulfilled', label: 'Fulfilled', tone: 'success' },
  { value: 'commitment_cancelled', label: 'Cancelled', tone: 'neutral' },
  { value: 'employment', label: 'Employment', tone: 'uncertain' },
  { value: 'meeting', label: 'Meeting', tone: 'neutral' },
  { value: 'document', label: 'Document', tone: 'neutral' },
]

export const KIND_META: Record<string, { label: string; tone: Tone }> = Object.fromEntries(TIMELINE_KINDS.map((k) => [k.value, { label: k.label, tone: k.tone }]))

export function kindMeta(kind: string): { label: string; tone: Tone } {
  return KIND_META[kind] ?? { label: kind.replace(/_/g, ' '), tone: 'neutral' }
}
