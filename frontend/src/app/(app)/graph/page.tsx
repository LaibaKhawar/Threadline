'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, ArrowRight, Ban, ExternalLink, Expand, LocateFixed, Maximize2, RotateCcw, Search, Shuffle, ZoomIn, ZoomOut } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'

import { GraphCanvas, type CanvasEdge, type CanvasNode, type GraphCanvasHandle, type Selection } from '@/components/memory/graph-canvas'
import { NODE_TYPES, nodeMeta, type NodeShape } from '@/components/memory/graph-style'
import { refHref } from '@/components/memory/ref-link'
import { useToast } from '@/components/toast'
import { AiLabel, Confidence, EvidenceChip, Quote } from '@/components/ui/ai'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, Label, LoadingRows, PageHeader, Spinner } from '@/components/ui/primitives'
import { errorMessage, get, post } from '@/lib/api'
import type { ProjectSummary } from '@/lib/types'
import type { GraphEdge, GraphNeighborhood, GraphNode, GraphOverview, GraphSearch, PeopleResponse } from '@/lib/types-memory'
import { cn, fmtDate } from '@/lib/utils'

const NODE_CAP = 250
const EXPAND_LIMIT = 40

type GState = { nodes: Record<string, GraphNode>; edges: Record<string, GraphEdge>; seeds: string[]; expanded: string[] }
type Filters = { types: string[] | null; from: string; to: string; asOf: string }

const EMPTY_FILTERS: Filters = { types: null, from: '', to: '', asOf: '' }

function splitId(id: string): [string, string] {
  const i = id.indexOf(':')
  return [id.slice(0, i), id.slice(i + 1)]
}

function neighbourhoodUrl(nodeId: string, f: Filters) {
  const [type, ref] = splitId(nodeId)
  const p = new URLSearchParams({ limit: String(EXPAND_LIMIT) })
  if (f.types) p.set('rel_types', f.types.join(','))
  if (f.asOf) p.set('as_of', `${f.asOf}T23:59:59Z`)
  if (f.from) p.set('date_from', `${f.from}T00:00:00Z`)
  if (f.to) p.set('date_to', `${f.to}T23:59:59Z`)
  return `/api/graph/node/${encodeURIComponent(type)}/${encodeURIComponent(ref)}?${p}`
}

/** Merge a neighbourhood into the graph, de-duplicating and respecting the node cap. */
function merge(g: GState, data: Pick<GraphNeighborhood, 'nodes' | 'edges'>, center: string | null): { next: GState; dropped: number } {
  const nodes = { ...g.nodes }
  let count = Object.keys(nodes).length
  let dropped = 0
  for (const n of data.nodes) {
    if (nodes[n.id]) {
      nodes[n.id] = { ...nodes[n.id], ...n }
      continue
    }
    if (count >= NODE_CAP && n.id !== center) {
      dropped++
      continue
    }
    nodes[n.id] = n
    count++
  }
  const edges = { ...g.edges }
  for (const e of data.edges) if (nodes[e.source] && nodes[e.target]) edges[e.id] = e
  const expanded = center && !g.expanded.includes(center) ? [...g.expanded, center] : g.expanded
  return { next: { ...g, nodes, edges, expanded }, dropped }
}

function fromOverview(o: GraphOverview): GState {
  return {
    nodes: Object.fromEntries(o.nodes.map((n) => [n.id, n])),
    edges: Object.fromEntries(o.edges.map((e) => [e.id, e])),
    seeds: o.nodes.map((n) => n.id),
    expanded: [],
  }
}

function edgeTime(e: GraphEdge) {
  return e.valid_from ?? e.observed_at
}

function edgeVisible(e: GraphEdge, f: Filters) {
  if (e.status === 'rejected') return false
  if (f.types && !f.types.includes(e.type)) return false
  const t = edgeTime(e)
  if (t && f.from && t < `${f.from}T00:00:00`) return false
  if (t && f.to && t > `${f.to}T23:59:59.999`) return false
  if (f.asOf) {
    const at = `${f.asOf}T23:59:59.999`
    // facts without a validity start count from when they were observed
    const start = e.valid_from ?? e.observed_at
    if (start && start > at) return false
    if (e.valid_to && e.valid_to <= at) return false
  }
  return true
}

function nodeDate(n: GraphNode) {
  return n.sent_at ?? n.start_at ?? n.decided_at ?? n.due_at ?? null
}

export default function GraphPage() {
  return (
    <Suspense fallback={<LoadingRows rows={6} />}>
      <GraphExplorer />
    </Suspense>
  )
}

function GraphExplorer() {
  const params = useSearchParams()
  const focus = params.get('focus')
  const toast = useToast()
  const qc = useQueryClient()
  const overview = useQuery({ queryKey: ['graph', 'overview'], queryFn: () => get<GraphOverview>('/api/graph/overview') })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => get<{ items: ProjectSummary[] }>('/api/projects') })
  const people = useQuery({ queryKey: ['people', ''], queryFn: () => get<PeopleResponse>('/api/people') })

  const [g, setG] = useState<GState | null>(null)
  const gRef = useRef<GState | null>(null)
  const commit = useCallback((next: GState) => {
    gRef.current = next
    setG(next)
  }, [])
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const filtersRef = useRef(filters)
  const [selected, setSelected] = useState<Selection>(null)
  const [pending, setPending] = useState<string[]>([])
  const [rebuilding, setRebuilding] = useState(false)
  const [centerOn, setCenterOn] = useState<string | null>(null)
  const canvas = useRef<GraphCanvasHandle>(null)
  const token = useRef(0)

  const expand = useCallback(
    async (nodeId: string, opts: { select?: boolean } = {}) => {
      setPending((p) => [...p, nodeId])
      try {
        const data = await get<GraphNeighborhood>(neighbourhoodUrl(nodeId, filtersRef.current))
        if (!gRef.current) return
        const { next, dropped } = merge(gRef.current, data, nodeId)
        commit(next)
        if (dropped > 0) toast(`Showing ${NODE_CAP} nodes at most: ${dropped} more neighbour${dropped === 1 ? '' : 's'} not added. Narrow the filters to see others.`, 'info')
        else if (data.nodes.length <= 1) toast('No further relationships for this node with the current filters.', 'info')
        if (opts.select) {
          setSelected({ kind: 'node', id: nodeId })
          setCenterOn(nodeId)
        }
      } catch (e) {
        toast(errorMessage(e), 'error')
      } finally {
        setPending((p) => p.filter((x) => x !== nodeId))
      }
    },
    [commit, toast],
  )

  // initial state from the overview (+ optional ?focus=type:id)
  const initialised = useRef(false)
  useEffect(() => {
    if (!overview.data || initialised.current) return
    initialised.current = true
    commit(fromOverview(overview.data))
    if (focus && focus.includes(':')) void expand(focus, { select: true })
  }, [overview.data, focus, expand, commit])

  // When filters change, rebuild: overview + re-expand what the user had expanded, with the new parameters.
  useEffect(() => {
    if (filtersRef.current === filters) return
    filtersRef.current = filters
    if (!overview.data || !gRef.current) return
    const my = ++token.current
    const prevExpanded = gRef.current.expanded
    let state = fromOverview(overview.data)
    commit(state)
    if (prevExpanded.length === 0) return
    setRebuilding(true)
    ;(async () => {
      try {
        for (const id of prevExpanded) {
          const data = await get<GraphNeighborhood>(neighbourhoodUrl(id, filters))
          if (my !== token.current) return
          state = merge(state, data, id).next
          commit(state)
        }
      } catch (e) {
        toast(errorMessage(e), 'error')
      } finally {
        if (my === token.current) setRebuilding(false)
      }
    })()
  }, [filters, overview.data, commit, toast])

  const projectColor = useMemo(() => Object.fromEntries((projects.data?.items ?? []).map((p) => [p.id, p.color])), [projects.data])
  const selfId = people.data?.items.find((p) => p.is_self)?.id

  const visible = useMemo(() => {
    if (!g) return { nodes: [] as GraphNode[], edges: [] as GraphEdge[] }
    const edges = Object.values(g.edges).filter((e) => edgeVisible(e, filters))
    const touched = new Set<string>()
    for (const e of edges) {
      touched.add(e.source)
      touched.add(e.target)
    }
    const nodes = Object.values(g.nodes).filter((n) => g.seeds.includes(n.id) || g.expanded.includes(n.id) || touched.has(n.id))
    return { nodes, edges }
  }, [g, filters])

  const canvasNodes = useMemo<CanvasNode[]>(
    () =>
      visible.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        label: n.label,
        color: n.type === 'project' ? projectColor[n.ref_id] : null,
        expanded: !!g?.expanded.includes(n.id),
        self: n.type === 'person' && n.ref_id === selfId,
      })),
    [visible.nodes, projectColor, g, selfId],
  )
  const canvasEdges = useMemo<CanvasEdge[]>(
    () => visible.edges.map((e) => ({ id: e.id, source: e.source, target: e.target, type: e.type, confidence: e.confidence, uncertain: e.confidence < 0.7, historical: !!e.valid_to || e.status === 'superseded' })),
    [visible.edges],
  )

  useEffect(() => {
    if (!centerOn) return
    const t = setTimeout(() => {
      canvas.current?.center(centerOn)
      setCenterOn(null)
    }, 550)
    return () => clearTimeout(t)
  }, [centerOn, canvasNodes])

  const reject = useMutation({
    mutationFn: (id: string) => post(`/api/graph/edges/${id}/reject`),
    onSuccess: (_r, id) => {
      if (gRef.current) {
        const edges = { ...gRef.current.edges }
        delete edges[id]
        commit({ ...gRef.current, edges })
      }
      setSelected((s) => (s?.kind === 'edge' && s.id === id ? null : s))
      toast('Relationship rejected. It’s hidden now and won’t be re-created by later processing.')
      qc.invalidateQueries({ queryKey: ['graph', 'overview'] })
      qc.invalidateQueries({ queryKey: ['person'] })
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })

  const typeCounts = useMemo(() => overview.data?.edge_type_counts ?? {}, [overview.data])
  const allTypes = useMemo(() => {
    const extra = g ? Object.values(g.edges).map((e) => e.type) : []
    return Array.from(new Set([...Object.keys(typeCounts), ...extra])).sort((a, b) => (typeCounts[b] ?? 0) - (typeCounts[a] ?? 0))
  }, [typeCounts, g])

  const selectNode = useCallback((id: string) => {
    setSelected({ kind: 'node', id })
    setCenterOn(id)
  }, [])

  const addFromSearch = (item: GraphSearch['items'][number]) => {
    if (gRef.current?.nodes[item.id]) {
      if (!gRef.current.expanded.includes(item.id)) void expand(item.id, { select: true })
      else selectNode(item.id)
      return
    }
    if (gRef.current) commit(merge(gRef.current, { nodes: [{ ...item }], edges: [] }, null).next)
    void expand(item.id, { select: true })
  }

  if (overview.isLoading) return <LoadingRows rows={8} />
  if (overview.error || !overview.data) return <ErrorState error={overview.error} retry={() => overview.refetch()} />

  const types = new Set(visible.nodes.map((n) => n.type))
  const typesInLegend = Object.keys(NODE_TYPES).filter((t) => types.has(t))

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Knowledge graph"
        description="How people, projects, meetings and documents connect. It starts from your projects and most-connected people; double-click a node (or use Expand) to load its neighbours."
      />

      <div className="mb-3 flex flex-wrap items-end gap-2">
        <GraphSearchBox onPick={addFromSearch} />
        <div>
          <Label htmlFor="as-of" hint="view the graph as it was">
            As of
          </Label>
          <div className="flex items-center gap-1">
            <Input id="as-of" type="date" className="h-8 w-40 text-xs" value={filters.asOf} onChange={(e) => setFilters((f) => ({ ...f, asOf: e.target.value }))} />
            {filters.asOf && (
              <Button size="sm" variant="ghost" onClick={() => setFilters((f) => ({ ...f, asOf: '' }))}>
                Now
              </Button>
            )}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1">
          {(rebuilding || pending.length > 0) && <Spinner className="mr-1" />}
          <span className="mr-2 text-xs tabular-nums text-ink-3">
            {visible.nodes.length} nodes · {visible.edges.length} relationships
            {visible.nodes.length >= NODE_CAP ? ` (cap ${NODE_CAP})` : ''}
          </span>
          <Button size="icon" variant="ghost" aria-label="Zoom in" title="Zoom in" onClick={() => canvas.current?.zoomIn()}>
            <ZoomIn className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="ghost" aria-label="Zoom out" title="Zoom out" onClick={() => canvas.current?.zoomOut()}>
            <ZoomOut className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="ghost" aria-label="Fit graph to view" title="Fit to view" onClick={() => canvas.current?.fit()}>
            <Maximize2 className="h-4 w-4" />
          </Button>
          <Button size="icon" variant="ghost" aria-label="Re-run layout" title="Re-run layout" onClick={() => canvas.current?.relayout()}>
            <Shuffle className="h-4 w-4" />
          </Button>
          <Button
            size="sm"
            variant="secondary"
            title="Back to the starting view"
            onClick={() => {
              token.current++
              setSelected(null)
              setFilters(EMPTY_FILTERS)
              filtersRef.current = EMPTY_FILTERS
              setRebuilding(false)
              void overview.refetch().then((r) => r.data && commit(fromOverview(r.data)))
            }}
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[210px_minmax(0,1fr)_320px]">
        <Card className="order-2 self-start lg:order-1">
          <CardHeader title="Filters" />
          <div className="space-y-4 p-3">
            <fieldset>
              <legend className="mb-1.5 flex w-full items-center justify-between text-xs font-medium text-ink-2">
                Relationship types
                <span className="flex gap-2 font-normal">
                  <button className="text-accent hover:underline" onClick={() => setFilters((f) => ({ ...f, types: null }))}>
                    All
                  </button>
                  <button className="text-accent hover:underline" onClick={() => setFilters((f) => ({ ...f, types: [] }))}>
                    None
                  </button>
                </span>
              </legend>
              <ul className="scrollbar-thin max-h-72 space-y-0.5 overflow-y-auto pr-1">
                {allTypes.map((t) => {
                  const on = !filters.types || filters.types.includes(t)
                  return (
                    <li key={t}>
                      <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-ink hover:bg-sunken">
                        <input
                          type="checkbox"
                          className="h-3.5 w-3.5 accent-[var(--accent)]"
                          checked={on}
                          onChange={() =>
                            setFilters((f) => {
                              const cur = f.types ?? allTypes
                              const next = on ? cur.filter((x) => x !== t) : [...cur, t]
                              return { ...f, types: next.length === allTypes.length ? null : next }
                            })
                          }
                        />
                        <span className="min-w-0 flex-1 truncate">{t.replace(/_/g, ' ').toLowerCase()}</span>
                        <span className="tabular-nums text-ink-3">{typeCounts[t] ?? ''}</span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            </fieldset>
            <fieldset className="space-y-2">
              <legend className="mb-1 text-xs font-medium text-ink-2">Observed between</legend>
              <div>
                <Label htmlFor="g-from">From</Label>
                <Input id="g-from" type="date" className="h-8 text-xs" value={filters.from} onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value }))} />
              </div>
              <div>
                <Label htmlFor="g-to">To</Label>
                <Input id="g-to" type="date" className="h-8 text-xs" value={filters.to} onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value }))} />
              </div>
              {(filters.from || filters.to) && (
                <Button size="sm" variant="ghost" onClick={() => setFilters((f) => ({ ...f, from: '', to: '' }))}>
                  Clear dates
                </Button>
              )}
            </fieldset>
            <div>
              <h3 className="mb-1.5 text-xs font-medium text-ink-2">Legend</h3>
              <ul className="space-y-1">
                {(typesInLegend.length ? typesInLegend : Object.keys(NODE_TYPES)).map((t) => (
                  <li key={t} className="flex items-center gap-2 text-xs text-ink-2">
                    <Swatch shape={NODE_TYPES[t].shape} color={NODE_TYPES[t].color} />
                    {NODE_TYPES[t].label}
                  </li>
                ))}
              </ul>
              <ul className="mt-2 space-y-1 text-[11px] text-ink-3">
                <li className="flex items-center gap-2">
                  <span className="w-5 border-t-2 border-line-strong" aria-hidden /> confident
                </li>
                <li className="flex items-center gap-2">
                  <span className="w-5 border-t-2 border-dashed border-line-strong" aria-hidden /> below 70% confidence
                </li>
                <li className="flex items-center gap-2">
                  <span className="w-5 border-t-2 border-dotted border-line-strong" aria-hidden /> no longer true
                </li>
              </ul>
            </div>
          </div>
        </Card>

        <Card className="order-1 h-[60vh] min-h-[420px] overflow-hidden lg:order-2 lg:h-[680px]">
          {visible.nodes.length === 0 && !rebuilding ? (
            <EmptyState title="Nothing to show" description={filters.types?.length === 0 ? 'All relationship types are filtered out.' : 'No nodes match these filters. Try widening the date range or clearing “as of”.'} />
          ) : (
            <GraphCanvas ref={canvas} nodes={canvasNodes} edges={canvasEdges} selected={selected} onSelect={setSelected} onExpand={(id) => void expand(id)} />
          )}
        </Card>

        <Card className="order-3 self-start lg:max-h-[680px] lg:overflow-y-auto">
          {g && selected?.kind === 'node' && g.nodes[selected.id] ? (
            <NodeInspector
              node={g.nodes[selected.id]}
              edges={visible.edges.filter((e) => e.source === selected.id || e.target === selected.id)}
              nodes={g.nodes}
              expanded={g.expanded.includes(selected.id)}
              expanding={pending.includes(selected.id)}
              onExpand={() => void expand(selected.id)}
              onSelectEdge={(id) => setSelected({ kind: 'edge', id })}
              onSelectNode={selectNode}
              onReject={(id) => reject.mutate(id)}
              rejecting={reject.isPending ? reject.variables : undefined}
            />
          ) : g && selected?.kind === 'edge' && g.edges[selected.id] ? (
            <EdgeInspector edge={g.edges[selected.id]} nodes={g.nodes} onSelectNode={selectNode} onReject={(id) => reject.mutate(id)} rejecting={reject.isPending} />
          ) : (
            <div>
              <CardHeader title="Inspector" />
              <div className="space-y-2 p-4 text-xs text-ink-2">
                <p>Select a node or a relationship to see what Threadline knows, where it came from and how confident it is.</p>
                <ul className="list-disc space-y-1 pl-4 text-ink-3">
                  <li>Click to select · double-click to expand</li>
                  <li>Scroll to zoom · drag the background to pan</li>
                  <li>Wrong relationship? Select it and reject it.</li>
                </ul>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}

function GraphSearchBox({ onPick }: { onPick: (item: GraphSearch['items'][number]) => void }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const dq = useDeferredValue(q.trim())
  const res = useQuery({ queryKey: ['graph', 'search', dq], queryFn: () => get<GraphSearch>(`/api/graph/search?q=${encodeURIComponent(dq)}`), enabled: dq.length > 0 })
  const items = res.data?.items ?? []
  return (
    <div className="relative w-full sm:w-80">
      <Label htmlFor="graph-search">Find a node</Label>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" aria-hidden />
        <Input
          id="graph-search"
          className="h-8 pl-8 text-xs"
          placeholder="Person, project, document, meeting…"
          value={q}
          autoComplete="off"
          role="combobox"
          aria-expanded={open && dq.length > 0}
          aria-controls="graph-search-results"
          onChange={(e) => {
            setQ(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && items[0]) {
              onPick(items[0])
              setOpen(false)
            }
            if (e.key === 'Escape') setOpen(false)
          }}
        />
      </div>
      {open && dq.length > 0 && (
        <ul id="graph-search-results" role="listbox" className="absolute z-30 mt-1 max-h-80 w-full overflow-y-auto rounded-md border border-line bg-surface py-1 shadow-pop">
          {res.isLoading && <li className="px-3 py-2 text-xs text-ink-3">Searching…</li>}
          {res.error && <li className="px-3 py-2 text-xs text-danger">{errorMessage(res.error)}</li>}
          {res.data && items.length === 0 && <li className="px-3 py-2 text-xs text-ink-3">No matching nodes.</li>}
          {items.map((it) => (
            <li key={it.id} role="option" aria-selected={false}>
              <button
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-sunken focus:bg-sunken focus:outline-none"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onPick(it)
                  setOpen(false)
                }}
              >
                <Swatch shape={nodeMeta(it.type).shape} color={nodeMeta(it.type).color} />
                <span className="min-w-0 flex-1 truncate text-ink">{it.label}</span>
                <span className="text-ink-3">{nodeMeta(it.type).label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Swatch({ shape, color }: { shape: NodeShape; color: string }) {
  const fill = `var(${color})`
  const s = 12
  const poly = (pts: string) => <polygon points={pts} fill={fill} />
  let el
  switch (shape) {
    case 'round-rectangle':
      el = <rect x="1" y="2" width="10" height="8" rx="2.5" fill={fill} />
      break
    case 'rectangle':
      el = <rect x="2" y="1.5" width="8" height="9" fill={fill} />
      break
    case 'hexagon':
      el = poly('3,1 9,1 12,6 9,11 3,11 0,6')
      break
    case 'diamond':
      el = poly('6,0 12,6 6,12 0,6')
      break
    case 'triangle':
    case 'round-triangle':
      el = poly('6,1 11.5,11 0.5,11')
      break
    case 'star':
      el = poly('6,0 7.5,4.2 12,4.4 8.4,7.1 9.7,11.5 6,8.9 2.3,11.5 3.6,7.1 0,4.4 4.5,4.2')
      break
    case 'tag':
      el = poly('0,2 8,2 12,6 8,10 0,10')
      break
    default:
      el = <circle cx="6" cy="6" r="5" fill={fill} />
  }
  return (
    <svg width={s} height={s} viewBox="0 0 12 12" aria-hidden className="shrink-0">
      {el}
    </svg>
  )
}

const DRAWER_TYPES = new Set(['email', 'event', 'document', 'note'])

function fmtValidity(e: GraphEdge) {
  if (!e.valid_from && !e.valid_to) return 'no validity period recorded'
  return `${e.valid_from ? fmtDate(e.valid_from) : 'unknown'} – ${e.valid_to ? fmtDate(e.valid_to) : 'now'}`
}

const ORIGIN_LABEL: Record<string, string> = {
  extraction: 'AI extraction',
  structural: 'From message metadata',
  user: 'You',
  rules: 'Rules',
}

function NodeInspector({
  node,
  edges,
  nodes,
  expanded,
  expanding,
  onExpand,
  onSelectEdge,
  onSelectNode,
  onReject,
  rejecting,
}: {
  node: GraphNode
  edges: GraphEdge[]
  nodes: Record<string, GraphNode>
  expanded: boolean
  expanding: boolean
  onExpand: () => void
  onSelectEdge: (id: string) => void
  onSelectNode: (id: string) => void
  onReject: (id: string) => void
  rejecting?: string
}) {
  const meta = nodeMeta(node.type)
  const href = refHref(node.type, node.ref_id)
  const date = nodeDate(node)
  return (
    <div>
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-ink-3">
          <Swatch shape={meta.shape} color={meta.color} /> {meta.label}
        </div>
        <h2 className="mt-1 break-words text-sm font-semibold text-ink">{node.label}</h2>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-3">
          {date && <span>{fmtDate(date)}</span>}
          {node.status && <Badge tone="neutral">{node.status}</Badge>}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Button size="sm" variant="primary" onClick={onExpand} loading={expanding}>
            <Expand className="h-3 w-3" /> {expanded ? 'Load neighbours again' : 'Expand neighbours'}
          </Button>
          {href && !DRAWER_TYPES.has(node.type) && (
            <Link href={href} className="inline-flex h-7 items-center gap-1 rounded-md border border-line px-2.5 text-xs font-medium text-ink hover:bg-sunken">
              Open {meta.label.toLowerCase()} <ExternalLink className="h-3 w-3" />
            </Link>
          )}
          {DRAWER_TYPES.has(node.type) && <EvidenceChip type={node.type} id={node.ref_id} label={`Preview ${meta.label.toLowerCase()}`} className="h-7 px-2.5 text-xs" />}
        </div>
      </div>
      <div className="px-4 py-2 text-xs font-medium text-ink-2">
        Relationships <span className="font-normal text-ink-3">({edges.length} shown)</span>
      </div>
      {edges.length === 0 ? (
        <p className="px-4 pb-4 text-xs text-ink-3">{expanded ? 'No relationships match the current filters.' : 'Expand to load this node’s relationships.'}</p>
      ) : (
        <ul className="divide-y divide-line border-t border-line">
          {edges.map((e) => {
            const outgoing = e.source === node.id
            const other = nodes[outgoing ? e.target : e.source]
            return (
              <li key={e.id} className="px-4 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <button className="min-w-0 text-left" onClick={() => onSelectEdge(e.id)} title="Inspect this relationship">
                    <span className="flex items-center gap-1 text-[11px] font-medium text-ink-3">
                      {outgoing ? <ArrowRight className="h-3 w-3" /> : <ArrowLeftRight className="h-3 w-3" />}
                      {e.type.replace(/_/g, ' ')}
                    </span>
                  </button>
                  <Button size="icon" variant="ghost" className="h-6 w-6" aria-label={`Reject relationship ${e.type} with ${other?.label ?? 'node'}`} title="Reject this relationship" loading={rejecting === e.id} onClick={() => onReject(e.id)}>
                    {rejecting === e.id ? null : <Ban className="h-3 w-3" />}
                  </Button>
                </div>
                {other && (
                  <button className="mt-0.5 block max-w-full truncate text-left text-sm text-ink hover:text-accent" onClick={() => onSelectNode(other.id)}>
                    {other.label}
                  </button>
                )}
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-3">
                  <Confidence value={e.confidence} />
                  <span>{fmtValidity(e)}</span>
                  <span>· {ORIGIN_LABEL[e.origin] ?? e.origin}</span>
                  {e.evidence && <EvidenceChip type={e.evidence.source_type} id={e.evidence.source_id} span={e.evidence.span} label="Evidence" />}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function EdgeInspector({ edge, nodes, onSelectNode, onReject, rejecting }: { edge: GraphEdge; nodes: Record<string, GraphNode>; onSelectNode: (id: string) => void; onReject: (id: string) => void; rejecting: boolean }) {
  const src = nodes[edge.source]
  const dst = nodes[edge.target]
  const props = Object.entries(edge.properties ?? {}).filter(([, v]) => v !== null && v !== '' && typeof v !== 'object')
  const inferred = edge.origin === 'extraction'
  return (
    <div>
      <div className="border-b border-line px-4 py-3">
        <div className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Relationship</div>
        <h2 className="mt-1 text-sm font-semibold text-ink">{edge.type.replace(/_/g, ' ')}</h2>
        <div className="mt-2 space-y-1 text-sm">
          <button className="block max-w-full truncate text-left text-ink hover:text-accent" onClick={() => onSelectNode(edge.source)}>
            {src?.label ?? edge.source}
          </button>
          <div className="flex items-center gap-1 text-xs text-ink-3">
            <ArrowRight className="h-3 w-3" /> {edge.type.replace(/_/g, ' ').toLowerCase()}
          </div>
          <button className="block max-w-full truncate text-left text-ink hover:text-accent" onClick={() => onSelectNode(edge.target)}>
            {dst?.label ?? edge.target}
          </button>
        </div>
      </div>
      <dl className="grid grid-cols-[92px_1fr] gap-x-3 gap-y-1.5 px-4 py-3 text-xs">
        <dt className="text-ink-3">Confidence</dt>
        <dd>
          <Confidence value={edge.confidence} />
        </dd>
        <dt className="text-ink-3">Status</dt>
        <dd>
          <Badge tone={edge.status === 'active' ? 'success' : 'neutral'}>{edge.status}</Badge>
        </dd>
        <dt className="text-ink-3">True during</dt>
        <dd className="text-ink-2">{fmtValidity(edge)}</dd>
        <dt className="text-ink-3">Learned</dt>
        <dd className="text-ink-2">{edge.observed_at ? fmtDate(edge.observed_at) : '—'}</dd>
        <dt className="text-ink-3">Origin</dt>
        <dd className="text-ink-2">{inferred ? <AiLabel>AI extraction</AiLabel> : (ORIGIN_LABEL[edge.origin] ?? edge.origin)}</dd>
        {props.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-3">{k.replace(/_/g, ' ')}</dt>
            <dd className="break-words text-ink-2">{String(v)}</dd>
          </div>
        ))}
      </dl>
      <div className="border-t border-line px-4 py-3">
        <div className="mb-1.5 text-xs font-medium text-ink-2">Evidence</div>
        {edge.evidence ? (
          <div className="space-y-2">
            {edge.evidence.span && <Quote>“{edge.evidence.span}”</Quote>}
            <EvidenceChip type={edge.evidence.source_type} id={edge.evidence.source_id} span={edge.evidence.span} label="Open source with passage highlighted" />
          </div>
        ) : (
          <p className="text-xs text-ink-3">Derived from message metadata (sender, recipients, attendees), not from a quoted passage.</p>
        )}
      </div>
      <div className={cn('border-t border-line px-4 py-3')}>
        <Button size="sm" variant="danger" loading={rejecting} onClick={() => onReject(edge.id)}>
          <Ban className="h-3 w-3" /> Reject this relationship
        </Button>
        <p className="mt-1.5 text-[11px] text-ink-3">Rejected relationships are hidden from the graph and graph-based retrieval, and later processing won’t recreate them.</p>
        <button className="mt-2 inline-flex items-center gap-1 text-[11px] text-accent hover:underline" onClick={() => onSelectNode(edge.source)}>
          <LocateFixed className="h-3 w-3" /> Back to {src?.label ?? 'source node'}
        </button>
      </div>
    </div>
  )
}
