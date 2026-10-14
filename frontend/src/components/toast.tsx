'use client'

import { CheckCircle2, AlertTriangle, X } from 'lucide-react'
import { type ReactNode, createContext, useCallback, useContext, useState } from 'react'

type Toast = { id: number; message: ReactNode; tone: 'success' | 'error' | 'info' }
const Ctx = createContext<(message: ReactNode, tone?: Toast['tone']) => void>(() => {})

export function useToast() {
  return useContext(Ctx)
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((message: ReactNode, tone: Toast['tone'] = 'success') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500)
  }, [])
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="animate-fade-in pointer-events-auto flex max-w-sm items-start gap-2 rounded-md border border-line bg-surface px-3 py-2 text-sm shadow-pop">
            {t.tone === 'error' ? <AlertTriangle className="mt-0.5 h-4 w-4 text-danger" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 text-success" />}
            <div className="flex-1 text-ink">{t.message}</div>
            <button aria-label="Dismiss" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))} className="text-ink-3 hover:text-ink">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
