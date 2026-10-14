'use client'

import Link from 'next/link'
import type { ReactNode } from 'react'

import { useSource } from '@/components/source-drawer'
import { SOURCE_ICON } from '@/components/ui/ai'
import { cn } from '@/lib/utils'

/** Where a memory reference lives in the app. Raw sources (email/meeting/document/note) open the source drawer instead. */
export function refHref(type: string | null | undefined, id: string | null | undefined): string | null {
  if (!type || !id) return null
  switch (type) {
    case 'person':
      return `/people/${id}`
    case 'project':
      return `/projects/${id}`
    case 'commitment':
      return `/commitments?id=${id}`
    case 'decision':
      return `/decisions?id=${id}`
    case 'task':
      return `/tasks?id=${id}`
    case 'document':
      return `/documents/${id}`
    case 'note':
      return `/notes?id=${id}`
    case 'thread':
      return `/inbox/${id}`
    default:
      return null
  }
}

const DRAWER_TYPES = new Set(['email', 'event', 'document', 'note'])

/**
 * Renders a link to a referenced memory item. Sources that the drawer can preview get an EvidenceChip
 * (with the optional span highlighted); structured records link to their page.
 */
export function RefLink({ type, id, label, span, className }: { type: string | null | undefined; id: string | null | undefined; label: ReactNode; span?: string | null; className?: string }) {
  const { open } = useSource()
  if (type && id && DRAWER_TYPES.has(type))
    return (
      <button type="button" onClick={() => open({ type, id, span: span ?? undefined })} title="Open source" className={cn('inline-flex min-w-0 items-center gap-1.5 text-left text-ink hover:text-accent hover:underline', className)}>
        <span className="shrink-0 text-ink-3">{SOURCE_ICON[type]}</span>
        <span className="min-w-0">{label}</span>
      </button>
    )
  const href = refHref(type, id)
  if (!href) return <span className={cn('text-ink-2', className)}>{label}</span>
  return (
    <Link href={href} className={cn('text-ink hover:text-accent hover:underline', className)}>
      {label}
    </Link>
  )
}
