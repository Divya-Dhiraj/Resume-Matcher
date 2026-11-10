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

interface PersonalInfo {
  name?: string;
  email?: string;
  phone?: string;
  location?: string;
  linkedin?: string;
}

interface CoverLetterData {
  coverLetter: string;
  personalInfo: PersonalInfo;
}

async function fetchCoverLetterData(resumeId: string): Promise<CoverLetterData> {
  const res = await fetch(`${API_BASE}/resumes?resume_id=${encodeURIComponent(resumeId)}`, {
    cache: 'no-store',
  });
  if (!res.ok) {
    throw new Error(`Failed to load resume (status ${res.status}).`);
  }
  const payload = (await res.json()) as {
    data: {
      cover_letter?: string;
      processed_resume?: {
        personalInfo?: PersonalInfo;
      };
    };
  };

  return {
    coverLetter: payload.data.cover_letter || '',
    personalInfo: payload.data.processed_resume?.personalInfo || {},
  };
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

  // Fetch cover letter data from API (same pattern as resume)
  const { coverLetter, personalInfo } = await fetchCoverLetterData(resolvedParams.id);

  // Margins are applied by Playwright's PDF renderer (not in CSS)
  // This keeps them consistent on every page

  // Get today's date formatted
  const today = new Date().toLocaleDateString(locale, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
  const nameFallback = translate(locale, 'resume.defaults.name');

  // Split cover letter into paragraphs — must match preview component logic
  const paragraphs = coverLetter.split('\n\n').filter((p) => p.trim().length > 0);

  return (
    <div
      className="cover-letter-print bg-white"
      style={{
        width: `${pageDims.width}mm`,
        maxHeight: `${pageDims.height}mm`,
        boxSizing: 'border-box',
        fontFamily: 'Georgia, "Times New Roman", serif',
        color: '#000000',
        overflow: 'hidden',
      }}
    >
      {/* Header - Personal Info */}
      <header
        style={{
          marginBottom: '6mm',
          paddingBottom: '3mm',
          borderBottom: '2px solid #000',
        }}
      >
        <h1
          style={{
            fontSize: '16pt',
            fontWeight: 'bold',
            margin: 0,
            letterSpacing: '-0.02em',
          }}
        >
          {personalInfo.name || nameFallback}
        </h1>
        <div
          style={{
            marginTop: '1.5mm',
            fontSize: '8.5pt',
            fontFamily: '"SF Mono", "Cascadia Code", "Fira Code", monospace',
            color: '#666',
            display: 'flex',
            flexWrap: 'wrap',
            gap: '4mm',
          }}
        >
          {personalInfo.email && <span>{personalInfo.email}</span>}
          {personalInfo.phone && <span>{personalInfo.phone}</span>}
          {personalInfo.location && <span>{personalInfo.location}</span>}
          {personalInfo.linkedin && <span>{personalInfo.linkedin}</span>}
        </div>
      </header>

      {/* Date */}
      <div
        style={{
          marginBottom: '6mm',
          fontSize: '9pt',
          fontFamily: '"SF Mono", "Cascadia Code", "Fira Code", monospace',
          color: '#666',
        }}
      >
        {today}
      </div>

      {/* Body */}
      <div style={{ lineHeight: '1.5' }}>
        {paragraphs.length > 0 ? (
          paragraphs.map((para, idx) => (
            <p
              key={idx}
              style={{
                fontSize: '10.5pt',
                margin: '0 0 3mm 0',
                textAlign: 'justify',
              }}
            >
              {para}
            </p>
          ))
        ) : (
          <p style={{ fontSize: '10.5pt', color: '#999' }}>
            {translate(locale, 'coverLetter.print.emptyContent')}
          </p>
        )}
      </div>
    </div>
  );
}
