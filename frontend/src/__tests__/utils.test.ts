import { describe, expect, it } from 'vitest'

import { bytes, cn, findSpan, fmtDate, initials, pct, relDays } from '@/lib/utils'

describe('utils', () => {
  it('finds evidence spans case- and whitespace-insensitively', () => {
    const text = 'Hi Laiba,\n\nI’ll send the   updated architecture document by Friday.'
    expect(findSpan(text, 'updated architecture document')).toEqual([text.indexOf('updated'), text.indexOf('updated') + 29])
    expect(findSpan(text, 'not present')).toBeNull()
    expect(findSpan(text, null)).toBeNull()
  })
  it('formats relative days against the workspace clock, not the browser clock', () => {
    const now = '2026-10-14T09:00:00Z'
    expect(relDays('2026-10-14T23:00:00Z', now)).toBe('today')
    expect(relDays('2026-10-15T11:00:00Z', now)).toBe('tomorrow')
    expect(relDays('2026-10-12T11:00:00Z', now)).toBe('2 days ago')
    expect(relDays('2026-08-14T11:00:00Z', now)).toBe('Aug 14, 2026')
  })
  it('formats numbers and names', () => {
    expect(pct(0.8235)).toBe('82%')
    expect(pct(null)).toBe('—')
    expect(bytes(2048)).toBe('2.0 KB')
    expect(initials('Sarah Chen')).toBe('SC')
    expect(fmtDate('2026-10-02T00:00:00Z')).toBe('Oct 2, 2026')
    expect(cn('px-2', 'px-4')).toBe('px-4')
  })
})
