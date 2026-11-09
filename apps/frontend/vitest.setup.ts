import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// jsdom 28 + Node 26 interop: Node's experimental built-in localStorage
// shadows jsdom's `window.localStorage`, and nothing populates a working
// `localStorage` on the global the way jsdom 27 used to. Install a
// minimal in-memory Storage polyfill so component tests that touch
// `localStorage.clear()` / `.getItem` / `.setItem` run in jsdom without
// relying on Node's `--localstorage-file` flag.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const installStorage = (target: typeof globalThis | Window): void => {
  if (!target) return;
  try {
    Object.defineProperty(target, 'localStorage', {
      value: new MemoryStorage(),
      writable: true,
      configurable: true,
    });
    Object.defineProperty(target, 'sessionStorage', {
      value: new MemoryStorage(),
      writable: true,
      configurable: true,
    });
  } catch {
    (target as unknown as Record<string, Storage>).localStorage = new MemoryStorage();
    (target as unknown as Record<string, Storage>).sessionStorage = new MemoryStorage();
  }
};

installStorage(globalThis);
if (typeof window !== 'undefined') {
  installStorage(window);
}

afterEach(() => {
  cleanup();
  try {
    globalThis.localStorage?.clear();
    globalThis.sessionStorage?.clear();
  } catch {
    /* ignore */
  }
});
