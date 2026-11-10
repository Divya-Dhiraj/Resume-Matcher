/**
 * Cover Letter Print Page
 *
 * This page renders a cover letter for PDF generation.
 * Uses the same API fetch pattern as the resume print page.
 */

import { API_BASE } from '@/lib/api/client';
import { translate } from '@/lib/i18n/server';
import { resolveLocale } from '@/lib/i18n/locale';

const PAGE_DIMENSIONS = {
  A4: { width: 210, height: 297 },
  LETTER: { width: 215.9, height: 279.4 },
} as const;

type PageSize = 'A4' | 'LETTER';

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams?: Promise<{
    pageSize?: string;
    lang?: string;
  }>;
};

async function fetchCoverLetter(resumeId: string): Promise<string> {
  const res = await fetch(`${API_BASE}/resumes?resume_id=${encodeURIComponent(resumeId)}`, {
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`Failed to load resume (status ${res.status}).`);
  }
  const payload = (await res.json()) as {
    data: { cover_letter?: string };
  };
  return payload.data.cover_letter || '';
}

function parsePageSize(value: string | undefined): PageSize {
  if (value === 'A4' || value === 'LETTER') {
    return value;
  }
  return 'A4';
}

export default async function PrintCoverLetterPage({ params, searchParams }: PageProps) {
  const resolvedParams = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;

  const pageSize = parsePageSize(resolvedSearchParams?.pageSize);
  const pageDims = PAGE_DIMENSIONS[pageSize];
  const locale = resolveLocale(resolvedSearchParams?.lang);

  const coverLetter = await fetchCoverLetter(resolvedParams.id);

  const paragraphs = coverLetter.split('\n\n').filter((p) => p.trim().length > 0);

  // Find the salutation line ("Dear …," / "Sehr geehrte …,") to split
  // header block (left-aligned, preserved line breaks) from body (justified).
  const salutationIdx = paragraphs.findIndex((p) =>
    /^(Dear |Sehr geehrte|To Whom|Estimad[oa])/i.test(p.trim())
  );
  const headerParagraphs = salutationIdx > 0 ? paragraphs.slice(0, salutationIdx) : [];
  const bodyParagraphs = salutationIdx > 0 ? paragraphs.slice(salutationIdx) : paragraphs;

  return (
    <div
      className="cover-letter-print bg-white"
      style={{
        width: `${pageDims.width}mm`,
        boxSizing: 'border-box',
        fontFamily: 'Georgia, "Times New Roman", serif',
        color: '#000000',
        lineHeight: '1.5',
      }}
    >
      {paragraphs.length > 0 ? (
        <>
          {/* Header block: sender, date, recipient, subject — left-aligned */}
          {headerParagraphs.map((para, idx) => (
            <p
              key={`h-${idx}`}
              style={{
                fontSize: '10pt',
                margin: '0 0 3mm 0',
                textAlign: 'left',
                whiteSpace: 'pre-line',
              }}
            >
              {para}
            </p>
          ))}
          {/* Body: salutation + paragraphs + sign-off — justified */}
          {bodyParagraphs.map((para, idx) => (
            <p
              key={`b-${idx}`}
              style={{
                fontSize: '10.5pt',
                margin: '0 0 3mm 0',
                textAlign: 'justify',
              }}
            >
              {para}
            </p>
          ))}
        </>
      ) : (
        <p style={{ fontSize: '10.5pt', color: '#999' }}>
          {translate(locale, 'coverLetter.print.emptyContent')}
        </p>
      )}
    </div>
  );
}
