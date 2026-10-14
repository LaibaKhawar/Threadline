import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { SourceProvider } from '@/components/source-drawer'
import { ChannelBadges, Confidence, EvidenceChip, InferenceCard, StatusBadge } from '@/components/ui/ai'
import { Dialog, EmptyState, ErrorState, Switch } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'

function wrap(ui: ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}><SourceProvider>{ui}</SourceProvider></QueryClientProvider>)
}

describe('AI transparency components', () => {
  it('labels commitment statuses in plain language', () => {
    render(<StatusBadge status="OVERDUE" />)
    expect(screen.getByText('Overdue')).toBeInTheDocument()
    render(<StatusBadge status="REJECTED" />)
    expect(screen.getByText('Not a commitment')).toBeInTheDocument()
  })
  it('shows confidence as a percentage with an accessible label', () => {
    render(<Confidence value={0.82} label="extraction confidence" />)
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByTitle('extraction confidence: 82%')).toBeInTheDocument()
  })
  it('inference card exposes confirm / change / ignore and the reasons', () => {
    const onConfirm = vi.fn()
    const onIgnore = vi.fn()
    render(<InferenceCard label="Project" value="Atlas" confidence={0.82} reasons={['title mentions “Atlas”']} onConfirm={onConfirm} onIgnore={onIgnore} />)
    expect(screen.getByText('title mentions “Atlas”')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    fireEvent.click(screen.getByRole('button', { name: /ignore/i }))
    expect(onConfirm).toHaveBeenCalledOnce()
    expect(onIgnore).toHaveBeenCalledOnce()
  })
  it('shows which retrieval channels found a result', () => {
    render(<ChannelBadges channels={{ vector: 2, graph: 1 }} />)
    expect(screen.getByText('semantic #2')).toBeInTheDocument()
    expect(screen.getByText('graph #1')).toBeInTheDocument()
  })
  it('evidence chip opens the source drawer', async () => {
    global.fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ id: 'e1', subject: 'Plan', from_addr: 'a@b.c', from_name: 'A', to: [], cc: [], sent_at: '2026-10-01T00:00:00Z', attachments: [], body: 'I will send the deck.' }), { headers: { 'content-type': 'application/json' } })) as typeof fetch
    wrap(<EvidenceChip type="email" id="e1" span="send the deck" label="Email “Plan”" />)
    fireEvent.click(screen.getByRole('button', { name: /plan/i }))
    expect(await screen.findByRole('dialog', { name: 'Source' })).toBeInTheDocument()
    expect(await screen.findByText('send the deck')).toHaveClass('evidence')
  })
})

describe('primitives', () => {
  it('switch is keyboard/screen-reader accessible', () => {
    const onChange = vi.fn()
    render(<Switch checked={false} onChange={onChange} label="Cloud AI" />)
    const sw = screen.getByRole('switch', { name: 'Cloud AI' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(sw)
    expect(onChange).toHaveBeenCalledWith(true)
  })
  it('dialog closes on Escape and renders in a portal', () => {
    const onClose = vi.fn()
    const { container } = render(<div><Dialog open onClose={onClose} title="Edit">body</Dialog></div>)
    expect(container.querySelector('[role=dialog]')).toBeNull()
    expect(screen.getByRole('dialog', { name: 'Edit' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
  it('error and empty states', () => {
    const retry = vi.fn()
    render(<ErrorState error={new ApiError(500, 'boom')} retry={retry} />)
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(retry).toHaveBeenCalled()
    render(<EmptyState title="Nothing overdue" />)
    expect(screen.getByText('Nothing overdue')).toBeInTheDocument()
  })
})
