// Threadline mark: one continuous thread passing through three memory points.
export function LogoMark({ className = 'h-6 w-6' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden fill="none">
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" className="fill-[var(--accent)]" />
      <path d="M6.5 21.5c4-9 8.5-9 11-4.5s6.5 4.5 8-6" stroke="var(--accent-ink)" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="6.5" cy="21.5" r="2.3" fill="var(--accent-ink)" />
      <circle cx="16.3" cy="14.6" r="2.3" fill="var(--accent-ink)" />
      <circle cx="25.5" cy="11" r="2.3" fill="var(--accent-ink)" />
    </svg>
  )
}

export function Wordmark({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <LogoMark />
      <span className="font-serif text-[17px] font-medium tracking-tight text-ink">Threadline</span>
    </span>
  )
}

export const TAGLINE = 'Your work, remembered — with receipts.'
