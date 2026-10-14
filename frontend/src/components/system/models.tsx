'use client'

import { CheckCircle2, XCircle } from 'lucide-react'

import { Badge, Label, Select } from '@/components/ui/primitives'
import type { ModelsHealth } from '@/lib/types-system'

/** Model status summary from GET /api/models/health. */
export function ModelHealthSummary({ health }: { health: ModelsHealth }) {
  const local = health.local
  const models = local.models ?? []
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-3">
      <div className="rounded-md border border-line p-3">
        <dt className="text-xs text-ink-3">Local runtime</dt>
        <dd className="mt-1 flex items-center gap-1.5 font-medium text-ink">
          {local.ok ? <CheckCircle2 className="h-4 w-4 text-success" /> : <XCircle className="h-4 w-4 text-danger" />}
          {local.provider} {local.ok ? 'reachable' : 'not reachable'}
        </dd>
        <dd className="mt-0.5 text-xs text-ink-3">
          {local.ok ? `${models.length} model${models.length === 1 ? '' : 's'} found${local.latency_ms !== undefined ? ` · ${local.latency_ms} ms` : ''}` : local.error ?? `Start Ollama at ${local.base_url ?? 'localhost:11434'}`}
        </dd>
      </div>
      <div className="rounded-md border border-line p-3">
        <dt className="text-xs text-ink-3">Embeddings</dt>
        <dd className="mt-1 truncate font-medium text-ink" title={health.embedder.model}>
          {health.embedder.model}
        </dd>
        <dd className="mt-0.5 text-xs text-ink-3">
          {health.embedder.provider} · {health.embedder.dim} dims · always local
        </dd>
      </div>
      <div className="rounded-md border border-line p-3">
        <dt className="text-xs text-ink-3">Cloud provider</dt>
        <dd className="mt-1 font-medium text-ink">{health.cloud.configured ? health.cloud.provider : 'Not configured'}</dd>
        <dd className="mt-0.5 text-xs text-ink-3">{health.cloud.configured ? 'Used only as your privacy mode allows' : 'No cloud calls are possible'}</dd>
      </div>
    </dl>
  )
}

/** Model select limited to models the local runtime reports; keeps the current value selectable even if missing. */
export function ModelSelect({ id, label, hint, value, models, onChange, disabled }: { id: string; label: string; hint?: string; value: string; models: string[]; onChange: (v: string) => void; disabled?: boolean }) {
  const list = models.filter((m) => !/embed/i.test(m))
  const missing = value && !list.includes(value)
  return (
    <div>
      <Label htmlFor={id} hint={hint}>
        {label}
      </Label>
      <Select id={id} className="w-full" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        {missing && <option value={value}>{value} (not installed)</option>}
        {list.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </Select>
      {missing && (
        <p className="mt-1 text-xs text-warning">
          <Badge tone="warning">Missing</Badge> Pull it with <code className="font-mono">ollama pull {value}</code> or pick an installed model.
        </p>
      )}
    </div>
  )
}
