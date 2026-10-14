'use client'

import type { Core, ElementDefinition, LayoutOptions } from 'cytoscape'
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'

import { Spinner } from '@/components/ui/primitives'

import { buildStylesheet } from './graph-style'

export type CanvasNode = { id: string; type: string; label: string; color?: string | null; expanded: boolean; self: boolean }
export type CanvasEdge = { id: string; source: string; target: string; type: string; confidence: number; uncertain: boolean; historical: boolean }
export type Selection = { kind: 'node' | 'edge'; id: string } | null
export type GraphCanvasHandle = { zoomIn: () => void; zoomOut: () => void; fit: () => void; center: (id: string) => void; relayout: () => void }

let fcoseRegistered = false

const short = (s: string) => (s.length > 32 ? `${s.slice(0, 30)}…` : s)

function layoutOptions(initial: boolean): LayoutOptions {
  return {
    name: 'fcose',
    quality: 'default',
    randomize: initial,
    animate: !initial,
    animationDuration: 450,
    fit: initial,
    padding: 40,
    nodeRepulsion: 7000,
    idealEdgeLength: 80,
    edgeElasticity: 0.35,
    nodeSeparation: 60,
    packComponents: true,
    tilingPaddingVertical: 28,
    tilingPaddingHorizontal: 56,
  } as unknown as LayoutOptions
}

/**
 * Cytoscape canvas. Cytoscape touches `window`, so it is imported dynamically on the client. Elements are
 * diffed into the existing instance (never rebuilt) so expanding a node keeps the rest of the layout stable.
 */
export const GraphCanvas = forwardRef<GraphCanvasHandle, { nodes: CanvasNode[]; edges: CanvasEdge[]; selected: Selection; onSelect: (s: Selection) => void; onExpand: (id: string) => void }>(
  function GraphCanvas({ nodes, edges, selected, onSelect, onExpand }, ref) {
    const el = useRef<HTMLDivElement>(null)
    const cyRef = useRef<Core | null>(null)
    const laidOut = useRef(false)
    const handlers = useRef({ onSelect, onExpand })
    const [ready, setReady] = useState(false)
    const [failed, setFailed] = useState<string | null>(null)

    useEffect(() => {
      handlers.current = { onSelect, onExpand }
    }, [onSelect, onExpand])

    useEffect(() => {
      let cancelled = false
      let cy: Core | null = null
      let ro: ResizeObserver | null = null
      let mo: MutationObserver | null = null
      ;(async () => {
        try {
          const [{ default: cytoscape }, { default: fcose }] = await Promise.all([import('cytoscape'), import('cytoscape-fcose')])
          if (!fcoseRegistered) {
            cytoscape.use(fcose)
            fcoseRegistered = true
          }
          if (cancelled || !el.current) return
          cy = cytoscape({
            container: el.current,
            style: buildStylesheet(),
            minZoom: 0.15,
            maxZoom: 3,
            boxSelectionEnabled: false,
            selectionType: 'single',
          })
          cy.on('tap', 'node', (e) => handlers.current.onSelect({ kind: 'node', id: e.target.id() }))
          cy.on('tap', 'edge', (e) => handlers.current.onSelect({ kind: 'edge', id: e.target.id() }))
          cy.on('tap', (e) => {
            if (e.target === cy) handlers.current.onSelect(null)
          })
          cy.on('dbltap', 'node', (e) => handlers.current.onExpand(e.target.id()))
          cy.on('mouseover', 'node, edge', () => el.current && (el.current.style.cursor = 'pointer'))
          cy.on('mouseout', 'node, edge', () => el.current && (el.current.style.cursor = ''))
          ro = new ResizeObserver(() => cy?.resize())
          ro.observe(el.current)
          // follow light/dark mode
          mo = new MutationObserver(() => cy?.style(buildStylesheet()))
          mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style', 'data-theme'] })
          cyRef.current = cy
          setReady(true)
        } catch (err) {
          setFailed(err instanceof Error ? err.message : 'Could not load the graph renderer')
        }
      })()
      return () => {
        cancelled = true
        ro?.disconnect()
        mo?.disconnect()
        cy?.destroy()
        cyRef.current = null
      }
    }, [])

    // Diff React state into the cytoscape instance.
    useEffect(() => {
      const cy = cyRef.current
      if (!cy || !ready) return
      const want = new Set<string>([...nodes.map((n) => n.id), ...edges.map((e) => e.id)])
      let addedNodes = 0
      cy.batch(() => {
        cy.elements().forEach((ele) => {
          if (!want.has(ele.id())) ele.remove()
        })
        const newNodes: ElementDefinition[] = []
        for (const n of nodes) {
          const data = { id: n.id, type: n.type, label: n.label, short: short(n.label), ...(n.color ? { color: n.color } : {}) }
          const ex = cy.getElementById(n.id)
          if (ex.nonempty()) {
            ex.data(data)
            ex.toggleClass('expanded', n.expanded)
            ex.toggleClass('self', n.self)
            continue
          }
          // place new nodes next to an already-placed neighbour so expansion grows outward
          const anchorEdge = edges.find((e) => (e.source === n.id && cy.getElementById(e.target).nonempty()) || (e.target === n.id && cy.getElementById(e.source).nonempty()))
          const anchorId = anchorEdge ? (anchorEdge.source === n.id ? anchorEdge.target : anchorEdge.source) : null
          const anchor = anchorId ? cy.getElementById(anchorId).position() : null
          const ext = cy.extent()
          const position = anchor
            ? { x: anchor.x + (Math.random() - 0.5) * 120, y: anchor.y + (Math.random() - 0.5) * 120 }
            : { x: (ext.x1 + ext.x2) / 2 + (Math.random() - 0.5) * 200, y: (ext.y1 + ext.y2) / 2 + (Math.random() - 0.5) * 200 }
          const cls = [n.expanded ? 'expanded' : '', n.self ? 'self' : ''].filter(Boolean).join(' ')
          newNodes.push({ group: 'nodes', data, position, classes: cls })
        }
        if (newNodes.length) cy.add(newNodes)
        addedNodes = newNodes.length
        const newEdges: ElementDefinition[] = []
        for (const e of edges) {
          const cls = [e.uncertain ? 'uncertain' : '', e.historical ? 'historical' : ''].filter(Boolean).join(' ')
          const ex = cy.getElementById(e.id)
          if (ex.nonempty()) {
            ex.classes(cls)
            continue
          }
          newEdges.push({ group: 'edges', data: { id: e.id, source: e.source, target: e.target, type: e.type.replace(/_/g, ' '), confidence: e.confidence }, classes: cls })
        }
        if (newEdges.length) cy.add(newEdges)
      })
      if (addedNodes > 0 && cy.nodes().length > 0) {
        const initial = !laidOut.current
        laidOut.current = true
        cy.layout(layoutOptions(initial)).run()
      }
    }, [nodes, edges, ready])

    // Selection + neighbourhood emphasis.
    useEffect(() => {
      const cy = cyRef.current
      if (!cy || !ready) return
      cy.batch(() => {
        cy.elements().unselect().removeClass('faded neighbor')
        if (!selected) return
        const target = cy.getElementById(selected.id)
        if (target.empty()) return
        target.select()
        const keep = selected.kind === 'node' ? target.closedNeighborhood() : target.union(target.connectedNodes())
        if (selected.kind === 'node') target.connectedEdges().addClass('neighbor')
        cy.elements().not(keep).addClass('faded')
      })
    }, [selected, ready, nodes, edges])

    useImperativeHandle(ref, () => ({
      zoomIn: () => cyRef.current?.animate({ zoom: { level: cyRef.current.zoom() * 1.3, renderedPosition: { x: cyRef.current.width() / 2, y: cyRef.current.height() / 2 } } }, { duration: 150 }),
      zoomOut: () => cyRef.current?.animate({ zoom: { level: cyRef.current.zoom() / 1.3, renderedPosition: { x: cyRef.current.width() / 2, y: cyRef.current.height() / 2 } } }, { duration: 150 }),
      fit: () => cyRef.current?.animate({ fit: { eles: cyRef.current.elements(), padding: 40 } }, { duration: 250 }),
      center: (id: string) => {
        const cy = cyRef.current
        const n = cy?.getElementById(id)
        if (cy && n && n.nonempty()) cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.1) }, { duration: 300 })
      },
      relayout: () => cyRef.current?.layout(layoutOptions(false)).run(),
    }))

    return (
      <div className="relative h-full w-full">
        <div ref={el} className="h-full w-full" role="img" aria-label={`Knowledge graph with ${nodes.length} nodes and ${edges.length} relationships. Use search or the inspector to navigate with the keyboard.`} />
        {!ready && !failed && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-xs text-ink-3">
            <Spinner /> Loading graph renderer…
          </div>
        )}
        {failed && <div className="absolute inset-0 flex items-center justify-center text-xs text-danger">{failed}</div>}
      </div>
    )
  },
)
