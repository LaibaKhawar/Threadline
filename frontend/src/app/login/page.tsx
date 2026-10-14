'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter, useSearchParams } from 'next/navigation'
import { type FormEvent, Suspense, useState } from 'react'

import { TAGLINE, Wordmark } from '@/components/logo'
import { Button, Input, Label } from '@/components/ui/primitives'
import { errorMessage, get, post } from '@/lib/api'

function LoginForm() {
  const router = useRouter()
  const params = useSearchParams()
  const qc = useQueryClient()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const next = params.get('next') || '/'
  const cfg = useQuery({ queryKey: ['auth-config'], queryFn: () => get<{ demo_login_enabled: boolean; allow_registration: boolean }>('/api/auth/config') })
  const done = () => {
    qc.clear()
    router.replace(next.startsWith('/') && !next.startsWith('//') ? next : '/')
  }
  const auth = useMutation({
    mutationFn: () => (mode === 'login' ? post('/api/auth/login', { email, password }) : post('/api/auth/register', { email, password, display_name: name })),
    onSuccess: done,
  })
  const demo = useMutation({ mutationFn: () => post('/api/auth/demo'), onSuccess: done })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    auth.mutate()
  }
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <Wordmark className="justify-center" />
          <p className="mt-3 text-sm text-ink-2">{TAGLINE}</p>
        </div>
        <form onSubmit={submit} className="space-y-3 rounded-lg border border-line bg-surface p-5 shadow-card" aria-label={mode === 'login' ? 'Sign in' : 'Create account'}>
          {mode === 'register' && (
            <div>
              <Label htmlFor="name">Your name</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
            </div>
          )}
          <div>
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </div>
          <div>
            <Label htmlFor="password" hint={mode === 'register' ? '(10+ characters)' : undefined}>
              Password
            </Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={mode === 'register' ? 10 : 1} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
          </div>
          {(auth.error || demo.error) && (
            <p role="alert" className="text-xs text-danger">
              {errorMessage(auth.error ?? demo.error)}
            </p>
          )}
          <Button type="submit" variant="primary" className="w-full" loading={auth.isPending}>
            {mode === 'login' ? 'Sign in' : 'Create account'}
          </Button>
          <button type="button" className="w-full text-center text-xs text-ink-2 hover:text-accent" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
            {mode === 'login' ? 'New here? Create a local account' : 'Have an account? Sign in'}
          </button>
        </form>
        {cfg.data?.demo_login_enabled && <div className="mt-4 rounded-lg border border-dashed border-line-strong p-4 text-center">
          <p className="text-xs text-ink-2">Explore with synthetic data: Alex Morgan’s fictional workspace.</p>
          <Button className="mt-2 w-full" onClick={() => demo.mutate()} loading={demo.isPending}>
            Open the demo workspace
          </Button>
        </div>}
        <p className="mt-6 text-center text-[11px] text-ink-3">Runs on your machine. Nothing leaves it unless you enable a cloud model.</p>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  )
}
