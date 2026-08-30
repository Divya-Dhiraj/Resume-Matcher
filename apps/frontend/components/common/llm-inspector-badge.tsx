'use client';

/**
 * LLM Inspector — always present on every default-layout page.
 *
 * Two states, no permanent dismiss:
 *   - "badge": small bottom-right pill showing live call count.
 *   - "panel": right-side sheet (480px) with the full inspector inside.
 *
 * Clicking the badge opens the panel in place — no new tab, no navigation.
 * The minimize control in the panel header collapses it back to a badge but
 * never hides it entirely, so the inspector stays one click away for the
 * whole session.
 *
 * The direct-link page at /debug/llm continues to work for bookmarking or
 * opening a call log full-screen.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from '@/lib/api/client';

const STORAGE_KEY = 'resume-matcher.llm-inspector.open';
const POLL_INTERVAL_MS = 3000;

interface LlmMessage {
  role: string;
  content: string;
}

interface LlmUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

interface LlmCall {
  id: string;
  timestamp: number;
  model: string | null;
  api_base: string | null;
  status: 'success' | 'failure' | string;
  error: string | null;
  latency_ms: number | null;
  usage: LlmUsage | null;
  messages: LlmMessage[];
  response: string;
  params: Record<string, unknown>;
}

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString();
}

function humanSize(chars: number): string {
  if (chars < 1000) return `${chars}c`;
  return `${(chars / 1000).toFixed(1)}kc`;
}

export const LlmInspectorBadge: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [calls, setCalls] = useState<LlmCall[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Read persisted open/closed after mount so SSR + first client render match.
  useEffect(() => {
    setMounted(true);
    try {
      setOpen(window.localStorage.getItem(STORAGE_KEY) === '1');
    } catch {
      /* ignore private-mode / policy blocks */
    }
  }, []);

  const setOpenPersisted = useCallback((next: boolean) => {
    setOpen(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, []);

  // Polling — cheapest possible loop. When minimized we still poll so the
  // badge's count stays live; the payload is small (cap 50 entries) and the
  // interval is 3s.
  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/debug/llm-calls`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setCalls(Array.isArray(data.calls) ? data.calls : []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    if (!mounted) return;
    void refresh();
    const id = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [mounted, refresh]);

  const clearAll = useCallback(async () => {
    if (!confirm('Clear all recorded LLM calls?')) return;
    await fetch(`${API_BASE}/debug/llm-calls`, { method: 'DELETE' });
    await refresh();
  }, [refresh]);

  const toggleCall = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const filtered = useMemo(() => {
    if (!filter.trim()) return calls;
    const needle = filter.toLowerCase();
    return calls.filter((c) => {
      if ((c.model ?? '').toLowerCase().includes(needle)) return true;
      if ((c.response ?? '').toLowerCase().includes(needle)) return true;
      for (const m of c.messages ?? []) {
        if ((m.content ?? '').toLowerCase().includes(needle)) return true;
      }
      return false;
    });
  }, [calls, filter]);

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard gated in some browsers */
    }
  };

  if (!mounted) return null;

  // ---------------- Minimized (badge) -----------------
  if (!open) {
    return (
      <button
        onClick={() => setOpenPersisted(true)}
        className="fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-2 bg-black text-white border border-black hover:bg-blue-700 hover:border-blue-700 transition-colors font-mono text-xs shadow-sw-default"
        title="Open LLM Inspector"
      >
        <span className="w-2 h-2 bg-green-400" aria-hidden />
        <span className="uppercase tracking-wider">LLM</span>
        <span className="tabular-nums text-white/80">{calls.length}</span>
      </button>
    );
  }

  // ---------------- Expanded (side panel) -----------------
  return (
    <aside
      className="fixed top-0 right-0 z-50 h-screen w-full sm:w-[480px] bg-white border-l border-black shadow-sw-lg flex flex-col"
      role="complementary"
      aria-label="LLM Inspector"
    >
      {/* Header */}
      <div className="border-b border-black p-3 space-y-2 shrink-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-green-400" aria-hidden />
            <span className="font-mono text-xs font-bold uppercase tracking-wider">
              LLM Inspector
            </span>
            <span className="font-mono text-[10px] text-steel-grey tabular-nums">
              {calls.length} call{calls.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={refresh}
              className="px-2 py-1 font-mono text-[10px] uppercase tracking-wider border border-black hover:bg-blue-700 hover:text-white hover:border-blue-700 transition-colors"
              title="Refresh"
            >
              ↻
            </button>
            <button
              onClick={clearAll}
              className="px-2 py-1 font-mono text-[10px] uppercase tracking-wider border border-black text-red-700 hover:bg-red-700 hover:text-white hover:border-red-700 transition-colors"
              title="Clear all"
            >
              clear
            </button>
            <button
              onClick={() => setOpenPersisted(false)}
              className="px-2 py-1 font-mono text-[10px] uppercase tracking-wider border border-black hover:bg-black hover:text-white transition-colors"
              title="Minimize to badge"
              aria-label="Minimize"
            >
              −
            </button>
          </div>
        </div>
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter by model or content…"
          className="w-full px-2 py-1 font-mono text-xs border border-steel-grey focus:border-blue-700 focus:outline-none"
        />
        {error && (
          <div className="p-2 font-mono text-[10px] text-red-700 bg-red-50 border border-red-700">
            {error}
          </div>
        )}
      </div>

      {/* Scrollable call list */}
      <div className="flex-1 overflow-auto p-2 space-y-2 bg-paper-tint">
        {filtered.length === 0 && (
          <div className="p-6 text-center font-mono text-[10px] text-steel-grey">
            No LLM calls captured yet. Trigger anything that runs the model —
            upload a resume, run tailoring, generate a cover letter — and calls
            will appear here.
          </div>
        )}
        {filtered.map((call) => {
          const isOpen = expanded.has(call.id);
          const promptChars = call.messages.reduce(
            (n, m) => n + (m.content?.length ?? 0),
            0
          );
          return (
            <div key={call.id} className="border border-black bg-white">
              <button
                onClick={() => toggleCall(call.id)}
                className="w-full p-2 text-left hover:bg-paper-tint transition-colors"
              >
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap min-w-0">
                    <span
                      className={`w-1.5 h-1.5 shrink-0 ${
                        call.status === 'success' ? 'bg-green-600' : 'bg-red-600'
                      }`}
                    />
                    <span className="font-mono text-[10px] font-bold">
                      {formatTime(call.timestamp)}
                    </span>
                    <span className="font-mono text-[10px] text-steel-grey truncate">
                      {call.model ?? '(no model)'}
                    </span>
                    {call.latency_ms !== null && (
                      <span className="font-mono text-[10px] text-steel-grey">
                        {call.latency_ms}ms
                      </span>
                    )}
                    {call.usage && (
                      <span className="font-mono text-[10px] text-steel-grey">
                        {call.usage.prompt_tokens}→{call.usage.completion_tokens}t
                      </span>
                    )}
                  </div>
                  <span className="font-mono text-[9px] text-steel-grey shrink-0">
                    {humanSize(promptChars)}→{humanSize(call.response.length)}
                  </span>
                </div>
              </button>

              {isOpen && (
                <div className="border-t border-black p-2 space-y-2 bg-white">
                  {call.error && (
                    <div className="p-2 font-mono text-[10px] text-red-700 bg-red-50 border border-red-700">
                      {call.error}
                    </div>
                  )}
                  {Object.keys(call.params).length > 0 && (
                    <div className="font-mono text-[9px] text-steel-grey break-all">
                      {JSON.stringify(call.params)}
                    </div>
                  )}
                  {call.messages.map((msg, i) => (
                    <div key={i} className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[9px] uppercase tracking-wider text-blue-700">
                          {msg.role} · {humanSize(msg.content.length)}
                        </span>
                        <button
                          onClick={() => copy(msg.content)}
                          className="font-mono text-[9px] text-steel-grey hover:text-blue-700"
                        >
                          copy
                        </button>
                      </div>
                      <pre className="p-2 font-mono text-[10px] leading-relaxed whitespace-pre-wrap bg-paper-tint border border-steel-grey max-h-[280px] overflow-auto">
                        {msg.content}
                      </pre>
                    </div>
                  ))}
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[9px] uppercase tracking-wider text-green-700">
                        response · {humanSize(call.response.length)}
                      </span>
                      <button
                        onClick={() => copy(call.response)}
                        className="font-mono text-[9px] text-steel-grey hover:text-blue-700"
                      >
                        copy
                      </button>
                    </div>
                    <pre className="p-2 font-mono text-[10px] leading-relaxed whitespace-pre-wrap bg-green-50 border border-green-700 max-h-[320px] overflow-auto">
                      {call.response || '(empty)'}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
};

export default LlmInspectorBadge;
