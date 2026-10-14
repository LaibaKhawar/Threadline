'use client'

import { Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/primitives'

export const ACCEPTED_EXT = ['.pdf', '.docx', '.txt', '.md', '.markdown', '.csv', '.xlsx', '.eml', '.ics', '.mbox']

export function DocStatus({ status, error }: { status: string; error?: string | null }) {
  if (status === 'ready') return <Badge tone="success">Ready</Badge>
  if (status === 'error' || status === 'failed')
    return (
      <Badge tone="danger" title={error ?? 'Processing failed'}>
        Error
      </Badge>
    )
  return (
    <Badge tone="info">
      <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> {status === 'processing' || status === 'pending' ? 'Processing' : status}
    </Badge>
  )
}

export function fileKind(mime: string, filename: string) {
  const ext = filename.includes('.') ? filename.split('.').pop()!.toUpperCase() : ''
  if (mime.includes('pdf')) return 'PDF'
  if (mime.includes('wordprocessing')) return 'Word'
  if (mime.includes('spreadsheet')) return 'Excel'
  if (mime.includes('csv')) return 'CSV'
  if (mime.includes('markdown')) return 'Markdown'
  if (mime.startsWith('text/')) return ext || 'Text'
  return ext || mime
}
