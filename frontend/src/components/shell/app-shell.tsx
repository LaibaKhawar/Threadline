'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  BarChart3,
  Bell,
  Bot,
  CalendarDays,
  CheckSquare,
  FileText,
  FolderKanban,
  Gauge,
  GitBranch,
  Handshake,
  History,
  Inbox,
  LayoutDashboard,
  LogOut,
  Moon,
  NotebookPen,
  Plug,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  Users,
  WifiOff,
  Workflow,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { type ReactNode, useEffect, useRef, useState } from 'react'

import { Wordmark } from '@/components/logo'
import { Badge, Kbd } from '@/components/ui/primitives'
import { ApiError, get, post } from '@/lib/api'
import { cn, fmtDate } from '@/lib/utils'

type Me = { user: { id: string; email: string; display_name: string; is_demo: boolean; onboarding_completed: boolean; ai_mode: string } }

const NAV: { group: string; items: { href: string; label: string; icon: ReactNode }[] }[] = [
  {
    group: 'Overview',
    items: [
      { href: '/', label: 'Dashboard', icon: <LayoutDashboard /> },
      { href: '/assistant', label: 'Assistant', icon: <Bot /> },
      { href: '/search', label: 'Search', icon: <Search /> },
    ],
  },
  {
    group: 'Work',
    items: [
      { href: '/inbox', label: 'Inbox', icon: <Inbox /> },
      { href: '/calendar', label: 'Calendar', icon: <CalendarDays /> },
      { href: '/projects', label: 'Projects', icon: <FolderKanban /> },
      { href: '/tasks', label: 'Tasks', icon: <CheckSquare /> },
      { href: '/commitments', label: 'Commitments', icon: <Handshake /> },
      { href: '/decisions', label: 'Decisions', icon: <GitBranch /> },
    ],
  },
  {
    group: 'Memory',
    items: [
      { href: '/people', label: 'People', icon: <Users /> },
      { href: '/graph', label: 'Knowledge graph', icon: <Workflow /> },
      { href: '/timeline', label: 'Timeline', icon: <History /> },
      { href: '/documents', label: 'Documents', icon: <FileText /> },
      { href: '/notes', label: 'Notes', icon: <NotebookPen /> },
    ],
  },
  {
    group: 'System',
    items: [
      { href: '/integrations', label: 'Integrations', icon: <Plug /> },
      { href: '/privacy', label: 'Privacy center', icon: <ShieldCheck /> },
      { href: '/activity', label: 'AI activity', icon: <Activity /> },
      { href: '/evaluation', label: 'Evaluation', icon: <BarChart3 /> },
      { href: '/settings', label: 'Settings', icon: <Settings /> },
    ],
  },
]

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const me = useQuery({ queryKey: ['me'], queryFn: () => get<Me>('/api/auth/me'), retry: false })
  const [paletteOpen, setPaletteOpen] = useState(false)

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`)
  }, [me.error, router, pathname])
  useEffect(() => {
    if (me.data && !me.data.user.onboarding_completed && pathname !== '/onboarding') router.replace('/onboarding')
  }, [me.data, router, pathname])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!me.data) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-ink-3" role="status">
        {me.error && !(me.error instanceof ApiError && me.error.status === 401) ? 'Can’t reach the Threadline API. Is the backend running?' : 'Loading…'}
      </div>
    )
  }
  return (
    <div className="flex min-h-screen overflow-x-clip">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <Sidebar pathname={pathname} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar me={me.data} onSearch={() => setPaletteOpen(true)} />
        <main id="main" className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 sm:px-8">
          {children}
        </main>
      </div>
      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} />}
    </div>
  )
}

function Sidebar({ pathname }: { pathname: string }) {
  return (
    <nav aria-label="Primary" className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line bg-bg-2 md:flex">
      <div className="px-4 pb-3 pt-4">
        <Link href="/" aria-label="Threadline home">
          <Wordmark />
        </Link>
      </div>
      <div className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-4">
        {NAV.map((g) => (
          <div key={g.group} className="mt-3">
            <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-3">{g.group}</div>
            {g.items.map((it) => {
              const active = it.href === '/' ? pathname === '/' : pathname.startsWith(it.href)
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors [&_svg]:h-4 [&_svg]:w-4',
                    active ? 'bg-surface font-medium text-ink shadow-card' : 'text-ink-2 hover:bg-sunken hover:text-ink',
                  )}
                >
                  <span className={active ? 'text-accent' : 'text-ink-3'}>{it.icon}</span>
                  {it.label}
                </Link>
              )
            })}
          </div>
        ))}
      </div>
    </nav>
  )
}

type SystemStatus = { internet: boolean; local_llm: boolean; mode: string }
type Notifs = { unread: number; items: { id: string; title: string; body: string; category: string; read: boolean; created_at: string; ref: { type: string | null; id: string | null } }[] }

function Topbar({ me, onSearch }: { me: Me; onSearch: () => void }) {
  const qc = useQueryClient()
  const router = useRouter()
  const { resolvedTheme, setTheme } = useTheme()
  const status = useQuery({ queryKey: ['system-status'], queryFn: () => get<SystemStatus>('/api/system/status'), refetchInterval: 60_000 })
  const notifs = useQuery({ queryKey: ['notifications'], queryFn: () => get<Notifs>('/api/notifications'), refetchInterval: 60_000 })
  const [open, setOpen] = useState(false)
  const [browserOnline, setBrowserOnline] = useState(true)
  useEffect(() => {
    const up = () => setBrowserOnline(navigator.onLine)
    up()
    window.addEventListener('online', up)
    window.addEventListener('offline', up)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', up)
    }
  }, [])
  const offline = !browserOnline || status.data?.internet === false
  const logout = async () => {
    await post('/api/auth/logout')
    qc.clear()
    router.replace('/login')
  }
  return (
    <header className="sticky top-0 z-30 flex h-12 items-center gap-3 border-b border-line bg-bg/90 px-4 backdrop-blur sm:px-8">
      <button onClick={onSearch} className="flex h-8 w-full max-w-md items-center gap-2 rounded-md border border-line bg-surface px-2.5 text-sm text-ink-3 hover:border-line-strong" aria-label="Search everything">
        <Search className="h-3.5 w-3.5" />
        <span className="min-w-0 flex-1 truncate text-left">Search people, projects, emails…</span>
        <span className="hidden sm:inline"><Kbd>⌘K</Kbd></span>
      </button>
      <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-2">
        {me.user.is_demo && (
          <Badge className="hidden lg:inline-flex" tone="uncertain" title="Synthetic data; the clock is pinned so the story is reproducible">
            Demo workspace
          </Badge>
        )}
        <Badge className="hidden sm:inline-flex" tone={me.user.ai_mode === 'LOCAL' ? 'success' : 'warning'} title="AI mode (Privacy center)">
          <ShieldCheck className="h-3 w-3" /> {me.user.ai_mode === 'LOCAL' ? 'Local only' : me.user.ai_mode === 'HYBRID' ? 'Hybrid' : 'Cloud'}
        </Badge>
        {offline && (
          <Badge tone="warning" title="No internet: local files, notes, tasks, search, graph and the local model still work. Connector sync is paused.">
            <WifiOff className="h-3 w-3" /> Offline
          </Badge>
        )}
        {status.data && !status.data.local_llm && (
          <Badge tone="neutral" title="No local model reachable: the assistant answers extractively from your data">
            <Gauge className="h-3 w-3" /> Model offline
          </Badge>
        )}
        <div className="relative">
          <button onClick={() => setOpen((v) => !v)} className="relative rounded-md p-1.5 text-ink-2 hover:bg-sunken" aria-label={`Notifications (${notifs.data?.unread ?? 0} unread)`}>
            <Bell className="h-4 w-4" />
            {!!notifs.data?.unread && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-danger" aria-hidden />}
          </button>
          {open && (
            <div className="animate-fade-in absolute right-0 top-9 w-[min(24rem,calc(100vw-2rem))] rounded-lg border border-line bg-surface shadow-pop">
              <div className="flex items-center justify-between border-b border-line px-3 py-2">
                <span className="text-sm font-medium">Notifications</span>
                <button
                  className="text-xs text-accent hover:underline"
                  onClick={async () => {
                    await post('/api/notifications/read-all')
                    qc.invalidateQueries({ queryKey: ['notifications'] })
                  }}
                >
                  Mark all read
                </button>
              </div>
              <ul className="scrollbar-thin max-h-96 overflow-y-auto">
                {(notifs.data?.items ?? []).length === 0 && <li className="p-4 text-center text-xs text-ink-3">You’re all caught up.</li>}
                {notifs.data?.items.map((n) => (
                  <li key={n.id} className={cn('border-b border-line px-3 py-2 last:border-0', !n.read && 'bg-accent-wash/40')}>
                    <p className="text-[13px] font-medium text-ink">{n.title}</p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-ink-2">{n.body}</p>
                    <p className="mt-1 text-[11px] text-ink-3">{fmtDate(n.created_at)}</p>
                  </li>
                ))}
              </ul>
              <div className="border-t border-line px-3 py-2 text-right">
                <Link href="/settings#notifications" className="text-xs text-ink-2 hover:text-accent" onClick={() => setOpen(false)}>
                  Notification settings
                </Link>
              </div>
            </div>
          )}
        </div>
        <button onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')} className="rounded-md p-1.5 text-ink-2 hover:bg-sunken" aria-label="Toggle theme">
          {resolvedTheme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
        <button onClick={logout} className="rounded-md p-1.5 text-ink-2 hover:bg-sunken" aria-label={`Sign out ${me.user.email}`} title={`Signed in as ${me.user.email}`}>
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}

type Quick = { groups: Record<string, { type: string; id: string; title: string; snippet: string; source_type?: string; source_id?: string }[]> }

const HREF: Record<string, (h: { id: string; source_id?: string }) => string> = {
  person: (h) => `/people/${h.id}`,
  project: (h) => `/projects/${h.id}`,
  email: (h) => `/search?open=email:${h.id}`,
  document: (h) => `/documents/${h.id}`,
  event: (h) => `/calendar?event=${h.id}`,
  note: (h) => `/notes?id=${h.id}`,
  commitment: () => `/commitments`,
  decision: () => `/decisions`,
  task: () => `/tasks`,
}

function CommandPalette({ onClose }: { onClose: () => void }) {
  const router = useRouter()
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => inputRef.current?.focus(), [])
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 200)
    return () => clearTimeout(t)
  }, [q])
  const res = useQuery({ queryKey: ['quick', debounced], queryFn: () => get<Quick>(`/api/search?k=12&q=${encodeURIComponent(debounced)}`), enabled: debounced.length > 1 })
  const go = (href: string) => {
    onClose()
    router.push(href)
  }
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-4 pt-[12vh]" onMouseDown={onClose}>
      <div role="dialog" aria-label="Quick search" className="animate-fade-in w-full max-w-xl overflow-hidden rounded-lg border border-line bg-surface shadow-pop" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Search className="h-4 w-4 text-ink-3" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose()
              if (e.key === 'Enter' && q.trim()) go(`/search?q=${encodeURIComponent(q.trim())}`)
            }}
            placeholder="Search, or press Enter for the full results page"
            className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-3"
            aria-label="Search query"
          />
          <Kbd>esc</Kbd>
        </div>
        <div className="scrollbar-thin max-h-[50vh] overflow-y-auto p-1">
          {debounced.length > 1 && res.isLoading && <p className="p-3 text-xs text-ink-3">Searching…</p>}
          {res.data &&
            Object.entries(res.data.groups).map(([type, hits]) => (
              <div key={type} className="py-1">
                <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-ink-3">{type}</div>
                {hits.slice(0, 4).map((h) => (
                  <button key={h.id} onClick={() => go((HREF[type] ?? (() => '/search'))(h))} className="block w-full rounded px-2 py-1.5 text-left hover:bg-sunken">
                    <div className="truncate text-sm text-ink">{h.title}</div>
                    <div className="truncate text-xs text-ink-3">{h.snippet}</div>
                  </button>
                ))}
              </div>
            ))}
          {!debounced && (
            <div className="p-3 text-xs text-ink-3">
              Try “What am I waiting on Ahmed for?” in the <button className="text-accent" onClick={() => go('/assistant')}>Assistant</button>, or search “architecture document”.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
