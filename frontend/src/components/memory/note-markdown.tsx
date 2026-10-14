'use client'

import type { ReactNode } from 'react'
import Markdown, { defaultUrlTransform, type Components } from 'react-markdown'

import { cn } from '@/lib/utils'

const WIKILINK = /\[\[([^\]\n]{1,120})\]\]/g
const PREFIX = 'wikilink:'

/** Titles referenced with [[Note title]] syntax, in order, de-duplicated. */
export function wikiLinks(body: string): string[] {
  const out: string[] = []
  for (const m of body.matchAll(WIKILINK)) {
    const t = m[1].trim()
    if (t && !out.some((x) => x.toLowerCase() === t.toLowerCase())) out.push(t)
  }
  return out
}

/**
 * Renders a note's markdown read-only. Raw HTML is never rendered. `[[Title]]` becomes a link that calls
 * `onOpenLink(title)`; unresolved links are styled differently so you can see they'd create a new note.
 */
export function NoteMarkdown({ body, onOpenLink, resolves }: { body: string; onOpenLink: (title: string) => void; resolves: (title: string) => boolean }) {
  const source = body.replace(WIKILINK, (_m, t: string) => `[${t.trim().replace(/[[\]]/g, '')}](${PREFIX}${encodeURIComponent(t.trim())})`)
  const components: Components = {
    a: ({ href, children }) => {
      if (href?.startsWith(PREFIX)) {
        const title = decodeURIComponent(href.slice(PREFIX.length))
        const ok = resolves(title)
        return (
          <button
            type="button"
            onClick={() => onOpenLink(title)}
            className={cn('rounded px-0.5 font-medium underline decoration-1 underline-offset-2', ok ? 'text-accent decoration-accent/40 hover:bg-accent-wash' : 'text-ink-3 decoration-dashed hover:text-accent')}
            title={ok ? `Open “${title}”` : `No note called “${title}” yet: click to create it`}
          >
            {children}
          </button>
        )
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline decoration-accent/40 underline-offset-2">
          {children}
        </a>
      )
    },
    h1: ({ children }) => <h1 className="mb-3 mt-1 font-serif text-xl font-medium text-ink">{children}</h1>,
    h2: ({ children }) => <h2 className="mb-2 mt-5 text-base font-semibold text-ink">{children}</h2>,
    h3: ({ children }) => <h3 className="mb-1.5 mt-4 text-sm font-semibold text-ink">{children}</h3>,
    p: ({ children }) => <p className="my-2 text-sm leading-relaxed text-ink">{children}</p>,
    ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 text-sm text-ink">{children}</ul>,
    ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5 text-sm text-ink">{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
    blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-line-strong pl-3 text-ink-2">{children}</blockquote>,
    code: ({ children }) => <code className="rounded bg-sunken px-1 py-0.5 font-mono text-[12px] text-ink">{children as ReactNode}</code>,
    pre: ({ children }) => <pre className="scrollbar-thin my-2 overflow-x-auto rounded-md bg-sunken p-3 text-[12px]">{children}</pre>,
    hr: () => <hr className="my-4 border-line" />,
    table: ({ children }) => <table className="my-2 text-sm">{children}</table>,
    img: ({ alt }) => <span className="text-xs text-ink-3">[image: {alt}]</span>,
  }
  return (
    <div className="min-w-0 break-words">
      <Markdown skipHtml urlTransform={(url) => (url.startsWith(PREFIX) ? url : defaultUrlTransform(url))} components={components}>
        {source}
      </Markdown>
    </div>
  )
}
