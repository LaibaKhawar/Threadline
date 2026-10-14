// Visual vocabulary for the knowledge graph. Colours are read from the design tokens at runtime so the
// canvas follows light/dark mode; only project colours (from the API) are literal values.
import type { StylesheetJson } from 'cytoscape'

export type NodeShape = 'ellipse' | 'round-rectangle' | 'hexagon' | 'diamond' | 'rectangle' | 'triangle' | 'star' | 'tag' | 'round-triangle'

export const NODE_TYPES: Record<string, { label: string; shape: NodeShape; color: string; size: number }> = {
  person: { label: 'Person', shape: 'ellipse', color: '--accent', size: 30 },
  project: { label: 'Project', shape: 'round-rectangle', color: '--warning', size: 38 },
  organization: { label: 'Organization', shape: 'hexagon', color: '--info', size: 30 },
  event: { label: 'Meeting', shape: 'diamond', color: '--success', size: 24 },
  email: { label: 'Email', shape: 'ellipse', color: '--ink-3', size: 16 },
  thread: { label: 'Thread', shape: 'ellipse', color: '--ink-3', size: 18 },
  document: { label: 'Document', shape: 'rectangle', color: '--uncertain', size: 24 },
  note: { label: 'Note', shape: 'rectangle', color: '--ink-2', size: 22 },
  commitment: { label: 'Commitment', shape: 'triangle', color: '--danger', size: 22 },
  decision: { label: 'Decision', shape: 'star', color: '--warning', size: 26 },
  task: { label: 'Task', shape: 'round-triangle', color: '--ink-2', size: 20 },
  topic: { label: 'Topic', shape: 'tag', color: '--ink-3', size: 20 },
}

export function nodeMeta(type: string) {
  return NODE_TYPES[type] ?? { label: type, shape: 'ellipse' as NodeShape, color: '--ink-3', size: 20 }
}

export function cssVar(name: string): string {
  if (typeof document === 'undefined') return '#888'
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'
}

/** Builds the cytoscape stylesheet from the current theme. */
export function buildStylesheet(): StylesheetJson {
  const v = (n: string) => cssVar(n)
  const typeRules = Object.entries(NODE_TYPES).map(([type, meta]) => ({
    selector: `node[type = "${type}"]`,
    style: { shape: meta.shape, 'background-color': v(meta.color), width: meta.size, height: meta.size },
  }))
  return [
    {
      selector: 'node',
      style: {
        label: 'data(short)',
        'font-size': 10,
        'font-family': 'ui-sans-serif, system-ui, sans-serif',
        color: v('--ink'),
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-outline-color': v('--bg'),
        'text-outline-width': 2,
        'text-max-width': '120px',
        'text-wrap': 'ellipsis',
        'border-width': 1,
        'border-color': v('--surface'),
        'min-zoomed-font-size': 7,
        'overlay-opacity': 0,
      },
    },
    ...typeRules,
    { selector: 'node[color]', style: { 'background-color': 'data(color)' } },
    { selector: 'node.expanded', style: { 'border-width': 2, 'border-color': v('--ink-2') } },
    { selector: 'node.self', style: { 'border-width': 3, 'border-color': v('--accent') } },
    {
      selector: 'node:selected',
      style: { 'border-width': 3, 'border-color': v('--accent'), 'font-weight': 'bold', 'z-index': 20 },
    },
    {
      selector: 'edge',
      style: {
        width: 'mapData(confidence, 0, 1, 0.6, 2.4)',
        'line-color': v('--line-strong'),
        'target-arrow-color': v('--line-strong'),
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.6,
        'curve-style': 'bezier',
        opacity: 0.85,
        'overlay-opacity': 0,
        'font-size': 8,
        color: v('--ink-3'),
        'text-outline-color': v('--bg'),
        'text-outline-width': 2,
        'text-rotation': 'autorotate',
      },
    },
    { selector: 'edge.uncertain', style: { 'line-style': 'dashed' } },
    { selector: 'edge.historical', style: { 'line-style': 'dotted', opacity: 0.6 } },
    { selector: 'edge.neighbor', style: { 'line-color': v('--ink-3'), 'target-arrow-color': v('--ink-3'), 'z-index': 10 } },
    {
      selector: 'edge:selected',
      style: { 'line-color': v('--accent'), 'target-arrow-color': v('--accent'), width: 3, label: 'data(type)', 'z-index': 30, color: v('--accent') },
    },
    { selector: '.faded', style: { opacity: 0.25 } },
  ]
}
