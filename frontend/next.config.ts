import path from 'node:path'
import type { NextConfig } from 'next'

// The browser talks only to this Next.js origin; /api/* is proxied to the FastAPI backend. Same-origin
// requests keep the session cookie HttpOnly + SameSite=Lax and make CSRF handling straightforward.
const backend = process.env.BACKEND_URL ?? 'http://localhost:8000'

const config: NextConfig = {
  output: 'standalone',
  outputFileTracingRoot: path.join(__dirname),
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }]
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'same-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ]
  },
}

export default config
