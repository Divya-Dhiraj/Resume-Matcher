import { ResumePreviewProvider } from '@/components/common/resume_previewer_context';
import { StatusCacheProvider } from '@/lib/context/status-cache';
import { LanguageProvider } from '@/lib/context/language-context';
import { LocalizedErrorBoundary } from '@/components/common/error-boundary';
import { LlmInspectorBadge } from '@/components/common/llm-inspector-badge';

export default function DefaultLayout({ children }: { children: React.ReactNode }) {
  return (
    <StatusCacheProvider>
      <LanguageProvider>
        <ResumePreviewProvider>
          <LocalizedErrorBoundary>
            <main className="min-h-screen flex flex-col">{children}</main>
            {/* Bottom-right floating badge on every default-layout page
                (dashboard, resume builder, tailor, tracker, settings…).
                Shows the current LLM-call count and opens the /debug/llm
                inspector in a new tab. Users can dismiss it (× button) —
                the page stays reachable at /debug/llm either way. */}
            <LlmInspectorBadge />
          </LocalizedErrorBoundary>
        </ResumePreviewProvider>
      </LanguageProvider>
    </StatusCacheProvider>
  );
}
