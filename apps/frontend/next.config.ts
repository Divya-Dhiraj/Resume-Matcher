import type { NextConfig } from 'next';

const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN || 'http://127.0.0.1:8000';

// Proxy timeout (ms). Set to the maximum any single request might need:
// bundled pipelines (tailor + cover letter + review) can run 3-5 LLM calls and
// need ~2× the base 240s. The per-request AbortController in lib/api/client.ts
// enforces tighter timeouts for non-bundled calls; the proxy just needs to not
// be the bottleneck. Driven by NEXT_PUBLIC_REQUEST_TIMEOUT_MS when set.
const rawTimeoutMs = process.env.NEXT_PUBLIC_REQUEST_TIMEOUT_MS;
const parsedTimeoutMs = rawTimeoutMs ? Number(rawTimeoutMs) : NaN;
const REQUEST_TIMEOUT_MS = Number.isFinite(parsedTimeoutMs)
  ? Math.min(1_800_000, Math.max(30_000, parsedTimeoutMs))
  : 480_000;

const nextConfig: NextConfig = {
  output: 'standalone',
  experimental: {
    proxyTimeout: REQUEST_TIMEOUT_MS,
    // Tree-shake barrel imports — saves ~200-800ms cold start per route
    optimizePackageImports: [
      'lucide-react',
      '@tiptap/react',
      '@tiptap/starter-kit',
      '@tiptap/extension-link',
      '@tiptap/extension-underline',
      '@dnd-kit/core',
      '@dnd-kit/sortable',
      '@dnd-kit/utilities',
    ],
  },
  async rewrites() {
    // Note: Next.js serves filesystem routes (app/api/) before rewrites.
    // Do not create app/api/ routes or they will shadow the backend proxy.
    return [
      {
        source: '/api/:path*',
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
      {
        source: '/docs',
        destination: `${BACKEND_ORIGIN}/docs`,
      },
      {
        source: '/redoc',
        destination: `${BACKEND_ORIGIN}/redoc`,
      },
      {
        source: '/openapi.json',
        destination: `${BACKEND_ORIGIN}/openapi.json`,
      },
    ];
  },
};

export default nextConfig;
