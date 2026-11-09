import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AdditionalForm } from '@/components/builder/forms/additional-form';
import { ResumeSingleColumn } from '@/components/resume/resume-single-column';
import type { AdditionalInfo, ResumeData } from '@/components/dashboard/resume-component';

// Components call useTranslations(); return the key so we can match deterministically.
vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({
    t: (key: string) => key,
  }),
}));

describe('AdditionalForm newline handling (issue #763)', () => {
  // technicalSkills now renders via SkillGroupsEditor (grouped blocks with
  // blur-commit semantics), so issue #763's "trailing-newline survives" guard
  // is pinned against `languages`, which is still a plain Textarea driven by
  // the same handleArrayChange/formatArray helpers from additional-form.tsx.

  it('preserves a trailing blank line so Enter can create a new item', () => {
    const onChange = vi.fn<(data: AdditionalInfo) => void>();
    const data: AdditionalInfo = { languages: ['English'] };

    render(<AdditionalForm data={data} onChange={onChange} />);

    const textarea = screen.getByLabelText('resume.sections.languages');
    fireEvent.change(textarea, { target: { value: 'English\n' } });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].languages).toEqual(['English', '']);
  });

  it('preserves a blank line between two items', () => {
    const onChange = vi.fn<(data: AdditionalInfo) => void>();
    const data: AdditionalInfo = {};

    render(<AdditionalForm data={data} onChange={onChange} />);

    const textarea = screen.getByLabelText('resume.sections.languages');
    fireEvent.change(textarea, { target: { value: 'English\n\nGerman' } });

    expect(onChange.mock.calls[0][0].languages).toEqual(['English', '', 'German']);
  });
});

describe('ResumeSingleColumn filters blank entries (issue #763)', () => {
  it('does not render empty/whitespace-only additional entries', () => {
    const data: ResumeData = {
      personalInfo: { name: 'Jane Doe' },
      additional: {
        technicalSkills: ['React', '', '   ', 'TypeScript'],
      },
    } as ResumeData;

    render(<ResumeSingleColumn data={data} />);

    // Blank entries must not produce stray separators in the joined output.
    expect(screen.getByText('React, TypeScript')).toBeInTheDocument();
    expect(screen.queryByText(/React, , /)).not.toBeInTheDocument();
  });
});
