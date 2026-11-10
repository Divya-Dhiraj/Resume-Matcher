'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { useTranslations } from '@/lib/i18n';

export interface CoverLetterPersonalInfo {
  name?: string;
  title?: string;
  email?: string;
  phone?: string;
  location?: string;
  website?: string;
  linkedin?: string;
  github?: string;
}

export interface CoverLetterPreviewProps {
  /** Cover letter content */
  content: string;
  /** Personal info for header */
  personalInfo: CoverLetterPersonalInfo;
  /** Page size for styling */
  pageSize?: 'A4' | 'LETTER';
  /** Additional class names */
  className?: string;
}

export function CoverLetterPreview({
  content,
  personalInfo: _pi,
  pageSize = 'A4',
  className,
}: CoverLetterPreviewProps) {
  const { t } = useTranslations();

  const paragraphs = content.split('\n\n').filter((p) => p.trim().length > 0);

  // Split header (sender, date, recipient, subject) from body at salutation
  const salutationIdx = paragraphs.findIndex((p) =>
    /^(Dear |Sehr geehrte|To Whom|Estimad[oa])/i.test(p.trim())
  );
  const headerParagraphs = salutationIdx > 0 ? paragraphs.slice(0, salutationIdx) : [];
  const bodyParagraphs = salutationIdx > 0 ? paragraphs.slice(salutationIdx) : paragraphs;

  return (
    <div
      className={cn(
        'bg-white border-2 border-black',
        'shadow-sw-default',
        'overflow-hidden',
        className
      )}
    >
      <div
        className={cn('p-8 md:p-12', pageSize === 'A4' ? 'min-h-[297mm]' : 'min-h-[11in]')}
        style={{
          maxWidth: pageSize === 'A4' ? '210mm' : '8.5in',
        }}
      >
        {paragraphs.length > 0 ? (
          <div className="space-y-4">
            {headerParagraphs.map((para, idx) => (
              <p
                key={`h-${idx}`}
                className="font-serif text-sm leading-relaxed text-ink-soft whitespace-pre-line"
              >
                {para}
              </p>
            ))}
            {bodyParagraphs.map((para, idx) => (
              <p
                key={`b-${idx}`}
                className="font-serif text-base leading-relaxed text-ink-soft text-justify"
              >
                {para}
              </p>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 text-steel-grey">
            <p className="font-mono text-sm">{t('coverLetter.preview.emptyTitle')}</p>
            <p className="font-mono text-xs mt-2">{t('coverLetter.preview.emptyDescription')}</p>
          </div>
        )}
      </div>
    </div>
  );
}
