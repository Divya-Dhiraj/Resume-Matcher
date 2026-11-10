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

/**
 * Classify each paragraph of an LLM-generated cover letter.
 * Expected order: sender block, date, recipient, subject, salutation, body…, closing, signature.
 */
type ParaRole = 'sender' | 'date' | 'recipient' | 'subject' | 'salutation' | 'body';

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

export function CoverLetterPreview({
  content,
  personalInfo: _pi,
  pageSize = 'A4',
  className,
}: CoverLetterPreviewProps) {
  const { t } = useTranslations();

  const paragraphs = content.split('\n\n').filter((p) => p.trim().length > 0);
  const classified = classifyParagraphs(paragraphs);

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
        {classified.length > 0 ? (
          <div className="space-y-3">
            {classified.map(({ text, role }, idx) => {
              const lines = text.split('\n');
              switch (role) {
                case 'sender':
                  return (
                    <div key={idx} className="whitespace-pre-line">
                      <p className="font-serif text-base font-bold leading-snug">{lines[0]}</p>
                      {lines.length > 1 && (
                        <p className="font-serif text-xs leading-relaxed text-ink-soft mt-0.5">
                          {lines.slice(1).join('\n')}
                        </p>
                      )}
                    </div>
                  );
                case 'date':
                  return (
                    <p key={idx} className="font-serif text-xs text-ink-soft text-right">
                      {text}
                    </p>
                  );
                case 'recipient':
                  return (
                    <p
                      key={idx}
                      className="font-serif text-xs leading-relaxed text-ink-soft whitespace-pre-line"
                    >
                      {text}
                    </p>
                  );
                case 'subject':
                  return (
                    <p key={idx} className="font-serif text-sm font-bold leading-snug">
                      {text}
                    </p>
                  );
                default:
                  return (
                    <p
                      key={idx}
                      className="font-serif text-sm leading-relaxed text-ink-soft text-justify"
                    >
                      {text}
                    </p>
                  );
              }
            })}
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
