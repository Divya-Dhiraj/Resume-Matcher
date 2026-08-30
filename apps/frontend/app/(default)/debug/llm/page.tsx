'use client';

/**
 * LLM Inspector — live view of what the model was sent and what it returned.
 *
 * Polls /api/v1/debug/llm-calls every 2s. Newest call is on top. Each call
 * expands to show the full messages array and the raw response string, so a
 * failed tailoring pass can be diagnosed without tailing docker logs.
 *
 * This is a live-debug convenience only — the backend keeps calls in memory
 * (see llm_audit.py), so a container restart wipes them.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE } from '@/lib/api/client';

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
  if (chars < 1000) return `${chars} chars`;
  return `${(chars / 1000).toFixed(1)}k chars`;
}

export default function LlmDebugPage() {
  const [calls, setCalls] = useState<LlmCall[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/debug/llm-calls`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setCalls(data.calls ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = window.setInterval(refresh, 2000);
    return () => window.clearInterval(id);
  }, [autoRefresh, refresh]);

  const clearAll = useCallback(async () => {
    if (!confirm('Clear all recorded LLM calls?')) return;
    await fetch(`${API_BASE}/debug/llm-calls`, { method: 'DELETE' });
    await refresh();
  }, [refresh]);

  const toggle = (id: string) => {
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
      // Clipboard may be gated in some browsers; nothing to do beyond noting it.
    }
  };

  return (
    <div className="min-h-screen bg-paper-tint p-4 md:p-8">
      <div className="max-w-5xl mx-auto space-y-4">
        <header className="border border-black bg-white p-4 shadow-sw-default">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h1 className="font-mono text-lg font-bold uppercase tracking-wider">
                LLM Inspector
              </h1>
              <p className="font-mono text-xs text-steel-grey">
                Last {calls.length} call{calls.length === 1 ? '' : 's'} · newest first · polls every 2s
              </p>
            </div>
            <div className="flex items-center gap-2">
              <label className="font-mono text-xs flex items-center gap-1 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                />
                auto-refresh
              </label>
              <button
                onClick={refresh}
                className="px-3 py-1 font-mono text-xs border border-black hover:bg-blue-700 hover:text-white hover:border-blue-700 transition-colors"
              >
                refresh
              </button>
              <button
                onClick={clearAll}
                className="px-3 py-1 font-mono text-xs border border-black text-red-700 hover:bg-red-700 hover:text-white hover:border-red-700 transition-colors"
              >
                clear
              </button>
            </div>
          </div>
          <div className="mt-3">
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="filter by model, prompt content, or response text…"
              className="w-full px-3 py-2 font-mono text-xs border border-steel-grey focus:border-blue-700 focus:outline-none"
            />
          </div>
          {error && (
            <div className="mt-3 p-2 font-mono text-xs text-red-700 bg-red-50 border border-red-700">
              Error: {error}
            </div>
          )}
        </header>

        {filtered.length === 0 && (
          <div className="border border-dashed border-steel-grey p-8 text-center font-mono text-xs text-steel-grey bg-white">
            No LLM calls captured yet. Trigger anything that runs the model (upload a resume,
            create an application, tailor) and this list will populate.
          </div>
        )}

        {filtered.map((call) => {
          const isOpen = expanded.has(call.id);
          const totalPromptChars = call.messages.reduce(
            (n, m) => n + (m.content?.length ?? 0),
            0
          );
          return (
            <div key={call.id} className="border border-black bg-white shadow-sw-default">
              <button
                onClick={() => toggle(call.id)}
                className="w-full p-3 text-left hover:bg-paper-tint transition-colors"
              >
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span
                      className={`w-2 h-2 ${
                        call.status === 'success' ? 'bg-green-600' : 'bg-red-600'
                      }`}
                    />
                    <span className="font-mono text-xs font-bold">{formatTime(call.timestamp)}</span>
                    <span className="font-mono text-xs text-steel-grey">
                      {call.model ?? '(no model)'}
                    </span>
                    {call.latency_ms !== null && (
                      <span className="font-mono text-xs text-steel-grey">{call.latency_ms}ms</span>
                    )}
                    {call.usage && (
                      <span className="font-mono text-xs text-steel-grey">
                        {call.usage.prompt_tokens}→{call.usage.completion_tokens} tok
                      </span>
                    )}
                  </div>
                  <span className="font-mono text-[10px] text-steel-grey">
                    prompt {humanSize(totalPromptChars)} · response {humanSize(call.response.length)}
                  </span>
                </div>
              </button>

              {isOpen && (
                <div className="border-t border-black p-3 space-y-3">
                  {call.error && (
                    <div className="p-2 font-mono text-xs text-red-700 bg-red-50 border border-red-700">
                      {call.error}
                    </div>
                  )}

                  {Object.keys(call.params).length > 0 && (
                    <div className="font-mono text-[10px] text-steel-grey">
                      params: {JSON.stringify(call.params)}
                    </div>
                  )}

                  {call.messages.map((msg, i) => (
                    <div key={i} className="space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[10px] uppercase tracking-wider text-blue-700">
                          {msg.role} · {humanSize(msg.content.length)}
                        </span>
                        <button
                          onClick={() => copy(msg.content)}
                          className="font-mono text-[10px] text-steel-grey hover:text-blue-700"
                        >
                          copy
                        </button>
                      </div>
                      <pre className="p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap bg-paper-tint border border-steel-grey max-h-[400px] overflow-auto">
                        {msg.content}
                      </pre>
                    </div>
                  ))}

                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-[10px] uppercase tracking-wider text-green-700">
                        response · {humanSize(call.response.length)}
                      </span>
                      <button
                        onClick={() => copy(call.response)}
                        className="font-mono text-[10px] text-steel-grey hover:text-blue-700"
                      >
                        copy
                      </button>
                    </div>
                    <pre className="p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap bg-green-50 border border-green-700 max-h-[500px] overflow-auto">
                      {call.response || '(empty)'}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
