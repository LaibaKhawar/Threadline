// Types for the System area (integrations, privacy, activity, evaluation, settings, onboarding).
// Mirrors backend/app/api/routers/system.py, assistant.py and core.py.

export type AiMode = 'LOCAL' | 'HYBRID' | 'CLOUD'

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'dead' | 'failed'

export type Job = {
  id: string
  kind: string
  status: JobStatus
  attempts: number
  progress: { percent?: number; message?: string; result?: Record<string, unknown> } | null
  error: string | null
  created_at: string | null
  finished_at: string | null
}

export type JobsResponse = { items: Job[]; events: { pending: number; failed: number } }
export type JobStart = { job_id: string; status?: string }

export type SyncStats = {
  cursor_present: boolean
  last_completed_at: string | null
  items_created: number
  items_updated: number
  items_deleted: number
  items_unchanged: number
  error_count: number
  rate_limit_remaining: number | null
}

export type Integration = {
  id: string
  kind: string
  name: string
  status: string
  config: Record<string, unknown>
  store_locally: boolean
  local_ai_allowed: boolean
  cloud_ai_allowed: boolean
  last_sync_at: string | null
  last_error: string | null
  created_at: string | null
  sync: SyncStats
  item_count?: number
  items?: number
}

export type CatalogItem = {
  kind: string
  name: string
  description: string
  item_kinds: string[]
  requires_network: boolean
  auth: string
  implemented: boolean
  incremental: boolean
  configured: boolean
}

export type Privacy = {
  ai_mode: AiMode
  cloud_configured: boolean
  cloud_model: string | null
  cloud_allowed_operations: string[]
  cloud_eligible_operations: string[]
  telemetry_opt_in: boolean
  telemetry_transmits: boolean
  sources: Integration[]
  llm_calls_by_locality: Record<string, number>
  embeddings: string
  stored_at: string
}

export type Inventory = { counts: Record<string, number> }

export type Settings = {
  reasoning_model: string
  extraction_model: string
  embedding: { provider: string; model: string; dim: number }
  llm_extraction_enabled: boolean
  timezone: string
  auto_create_tasks: boolean
  procedural_prefs: string[]
  clock_override: string | null
  ollama_url: string
}

export type ModelsHealth = {
  local: { provider: string; ok: boolean; models?: string[]; latency_ms?: number; base_url?: string; error?: string }
  cloud: { configured: boolean; provider: string | null }
  embedder: { provider: string; model: string; dim: number }
}

export type AuditItem = { id: string; actor: string; action: string; target: { type: string | null; id: string | null }; details: Record<string, unknown> | null; created_at: string }
export type RunItem = {
  id: string
  question: string
  status: string
  mode: string | null
  latency_ms: number | null
  model: string | null
  citations: number
  verification: Record<string, unknown> | null
  tokens: number
  cost_usd: number | null
  created_at: string
}
export type ToolItem = { id: string; run_id: string; tool: string; access: string; status: string; latency_ms: number | null; result_count: number | null; created_at: string }
export type LlmItem = {
  id: string
  provider: string
  model: string
  locality: 'local' | 'cloud' | string
  operation: string | null
  status: string
  input_tokens: number
  output_tokens: number
  cost_usd: number | null
  latency_ms: number | null
  source_types: string[] | null
  created_at: string
}

export type ToolManifest = {
  name: string
  description: string
  access: 'READ' | 'WRITE' | string
  scope: string
  sensitivity: string
  requires_approval: boolean
  params: Record<string, string>
}

export type Proposal = {
  id: string
  tool: string
  payload: Record<string, unknown>
  reason: string | null
  status: string
  result: Record<string, unknown> | null
  created_at: string | null
  decided_at: string | null
  permission: ToolManifest | null
}

export type CostBucket = { calls: number; input_tokens: number; output_tokens: number; cost_usd: number; avg_latency_ms: number }
export type Costs = {
  periods: Record<'today' | 'week' | 'month', Record<string, CostBucket>>
  per_run: { run_id: string; question: string; tokens: number; cost_usd: number | null; latency_ms: number | null }[]
  note: string
}

export type EvalRun = { id: string; suite: string; config: Record<string, unknown> | null; metrics: Record<string, unknown>; created_at: string }
export type EvalHistoryItem = { id: string; suite: string; variant: string | null; metrics: Record<string, unknown>; created_at: string }
export type Evaluation = { latest: EvalRun[]; history: EvalHistoryItem[] }
export type EvalDetail = EvalRun & { details: unknown }

export type NotificationCategory = { key: string; label: string; enabled: boolean }
