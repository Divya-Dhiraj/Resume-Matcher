/**
 * Cover Letter Print Page
 *
 * Renders a cover letter for PDF generation following DIN 5008 formatting:
 * sender name bold, date right-aligned, subject bold, body justified.
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

type ParaRole = 'sender' | 'date' | 'recipient' | 'subject' | 'body';

function classifyParagraphs(paragraphs: string[]): Array<{ text: string; role: ParaRole }> {
  const salutationIdx = paragraphs.findIndex((p) =>
    /^(Dear |Sehr geehrte|To Whom|Estimad[oa])/i.test(p.trim())
  );

  if (salutationIdx <= 0) {
    return paragraphs.map((text) => ({ text, role: 'body' as ParaRole }));
  }

  return paragraphs.map((text, idx) => {
    if (idx >= salutationIdx) return { text, role: 'body' as ParaRole };
    if (idx === 0) return { text, role: 'sender' as ParaRole };
    if (/^\d{1,2}[\s./]/.test(text.trim()) || /\b\d{4}$/.test(text.trim()))
      return { text, role: 'date' as ParaRole };
    if (/^(Re:|Betreff:|Subject:|Ref[.:])/.test(text.trim()))
      return { text, role: 'subject' as ParaRole };
    return { text, role: 'recipient' as ParaRole };
  });
}

export default async function PrintCoverLetterPage({ params, searchParams }: PageProps) {
  const resolvedParams = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;

  const pageSize = parsePageSize(resolvedSearchParams?.pageSize);
  const pageDims = PAGE_DIMENSIONS[pageSize];
  const locale = resolveLocale(resolvedSearchParams?.lang);

  const coverLetter = await fetchCoverLetter(resolvedParams.id);
  const paragraphs = coverLetter.split('\n\n').filter((p) => p.trim().length > 0);
  const classified = classifyParagraphs(paragraphs);

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
      {classified.length > 0 ? (
        <>
          {classified.map(({ text, role }, idx) => {
            const lines = text.split('\n');
            switch (role) {
              case 'sender':
                return (
                  <div key={idx} style={{ marginBottom: '3mm', whiteSpace: 'pre-line' }}>
                    <p
                      style={{
                        fontSize: '12pt',
                        fontWeight: 'bold',
                        margin: 0,
                        lineHeight: '1.3',
                      }}
                    >
                      {lines[0]}
                    </p>
                    {lines.length > 1 && (
                      <p style={{ fontSize: '9pt', margin: '1mm 0 0 0', lineHeight: '1.4' }}>
                        {lines.slice(1).join('\n')}
                      </p>
                    )}
                  </div>
                );
              case 'date':
                return (
                  <p
                    key={idx}
                    style={{
                      fontSize: '10pt',
                      margin: '0 0 3mm 0',
                      textAlign: 'right',
                    }}
                  >
                    {text}
                  </p>
                );
              case 'recipient':
                return (
                  <p
                    key={idx}
                    style={{
                      fontSize: '10pt',
                      margin: '0 0 3mm 0',
                      whiteSpace: 'pre-line',
                      lineHeight: '1.4',
                    }}
                  >
                    {text}
                  </p>
                );
              case 'subject':
                return (
                  <p
                    key={idx}
                    style={{
                      fontSize: '11pt',
                      fontWeight: 'bold',
                      margin: '0 0 3mm 0',
                    }}
                  >
                    {text}
                  </p>
                );
              default:
                return (
                  <p
                    key={idx}
                    style={{
                      fontSize: '10.5pt',
                      margin: '0 0 3mm 0',
                      textAlign: 'justify',
                    }}
                  >
                    {text}
                  </p>
                );
            }
          })}
        </>
      ) : (
        <p style={{ fontSize: '10.5pt', color: '#999' }}>
          {translate(locale, 'coverLetter.print.emptyContent')}
        </p>
      )}
    </div>
  );
}
