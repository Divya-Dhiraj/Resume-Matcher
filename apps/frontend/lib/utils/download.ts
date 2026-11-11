declare global {
  interface Window {
    showSaveFilePicker?: (options?: {
      suggestedName?: string;
      types?: Array<{ description: string; accept: Record<string, string[]> }>;
    }) => Promise<FileSystemFileHandle>;
  }
}

const _fileHandles = new Map<string, FileSystemFileHandle>();

export function hasSavedFileHandle(key = 'resume'): boolean {
  return _fileHandles.has(key);
}

export function clearSavedFileHandles(): void {
  _fileHandles.clear();
}

export async function saveToLocalFile(
  blob: Blob,
  suggestedName: string,
  key = 'resume'
): Promise<boolean> {
  if (typeof window === 'undefined' || !('showSaveFilePicker' in window)) {
    return false;
  }
  try {
    let handle = _fileHandles.get(key);
    if (!handle) {
      handle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description: 'PDF', accept: { 'application/pdf': ['.pdf'] } }],
      });
      _fileHandles.set(key, handle);
    }
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return true;
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'AbortError') return false;
    _fileHandles.delete(key);
    throw e;
  }
}

export function downloadBlobAsFile(blob: Blob, filename: string): void {
  if (typeof document === 'undefined') return;
  if (!document.body) return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(url);
    link.remove();
  }, 1000);
}

export function openUrlInNewTab(url: string): boolean {
  if (typeof window === 'undefined') return false;
  const newWindow = window.open(url, '_blank', 'noopener,noreferrer');
  if (newWindow) {
    newWindow.opener = null;
    return true;
  }
  return false;
}

/**
 * Sanitize a resume title for use as a filename
 * - Removes/replaces invalid filename characters
 * - Truncates to reasonable length
 * - Provides fallback if title is empty
 */
export function sanitizeFilename(
  title: string | null | undefined,
  fallbackId: string,
  type: 'resume' | 'cover-letter' = 'resume'
): string {
  // Use fallback if no title
  if (!title?.trim()) {
    return type === 'resume' ? `resume_${fallbackId}.pdf` : `cover_letter_${fallbackId}.pdf`;
  }

  // Normalize Unicode to NFC form to ensure consistent representation
  // This ensures "Currículum" (NFD: i + combining accent) and "Currículum" (NFC: í as single char) produce the same filename
  let sanitized = title.normalize('NFC').trim();

  // Remove or replace invalid characters: / \ : * ? " < > |
  sanitized = sanitized
    .replace(/[/\\:*?"<>|]/g, '-') // Replace invalid chars with dash
    .replace(/\s+/g, ' ') // Normalize whitespace
    .trim();

  // Truncate to 100 characters using Array.from() to handle multi-byte characters correctly
  // This prevents splitting multi-byte UTF-8 characters (Chinese, Japanese, emoji) mid-sequence
  const chars = Array.from(sanitized); // Handles grapheme clusters properly
  if (chars.length > 100) {
    sanitized = chars.slice(0, 100).join('').trim();
  }

  // Add .pdf extension
  return `${sanitized}.pdf`;
}

/**
 * Build a personalized download filename for resume or cover letter PDFs.
 * Format: "{Name} - {Type} - {Company}.pdf" (falls back gracefully when data is missing)
 */
export function buildResumeFilename(
  name: string | null | undefined,
  company: string | null | undefined,
  fallbackId: string,
  type: 'resume' | 'cover-letter' = 'resume'
): string {
  const typeLabel = type === 'resume' ? 'Resume' : 'Cover Letter';
  const cleanName = name?.trim() || null;
  const cleanCompany = company?.trim() || null;

  let raw: string;
  if (cleanName && cleanCompany) {
    raw = `${cleanName} - ${typeLabel} - ${cleanCompany}`;
  } else if (cleanName) {
    raw = `${cleanName} - ${typeLabel}`;
  } else {
    return sanitizeFilename(
      cleanCompany ? `${typeLabel} - ${cleanCompany}` : null,
      fallbackId,
      type
    );
  }

  return sanitizeFilename(raw, fallbackId, type);
}
