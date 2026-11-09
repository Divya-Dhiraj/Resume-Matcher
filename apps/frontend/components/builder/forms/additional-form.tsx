'use client';

import React, { useState } from 'react';
import { Pencil, Check, X } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { AdditionalInfo } from '@/components/dashboard/resume-component';
import { useTranslations } from '@/lib/i18n';
import { GroupedBlocksEditor } from './grouped-blocks-editor';

interface AdditionalFormProps {
  data: AdditionalInfo;
  onChange: (data: AdditionalInfo) => void;
}

// Which fields have a renameable rendered heading. Keys are the AdditionalInfo
// field names on the frontend TS interface; labelKey is the corresponding key
// inside `additional.labels` (mirrored from backend AdditionalSectionLabels
// which uses `certifications` rather than `certificationsTraining`).
const RENAMEABLE_FIELDS: {
  field: 'technicalSkills' | 'languages' | 'certificationsTraining' | 'awards';
  labelKey: 'technicalSkills' | 'languages' | 'certifications' | 'awards';
  defaultI18nKey: string;
  placeholderI18nKey: string;
  fieldIdSuffix: string;
}[] = [
  {
    field: 'technicalSkills',
    labelKey: 'technicalSkills',
    defaultI18nKey: 'resume.additional.technicalSkills',
    placeholderI18nKey: 'builder.additionalForm.placeholders.technicalSkills',
    fieldIdSuffix: 'technicalSkills',
  },
  {
    field: 'languages',
    labelKey: 'languages',
    defaultI18nKey: 'resume.sections.languages',
    placeholderI18nKey: 'builder.additionalForm.placeholders.languages',
    fieldIdSuffix: 'languages',
  },
  {
    field: 'certificationsTraining',
    labelKey: 'certifications',
    defaultI18nKey: 'resume.sections.certifications',
    placeholderI18nKey: 'builder.additionalForm.placeholders.certifications',
    fieldIdSuffix: 'certifications',
  },
  {
    field: 'awards',
    labelKey: 'awards',
    defaultI18nKey: 'resume.sections.awards',
    placeholderI18nKey: 'builder.additionalForm.placeholders.awards',
    fieldIdSuffix: 'awards',
  },
];

export const AdditionalForm: React.FC<AdditionalFormProps> = ({ data, onChange }) => {
  const { t } = useTranslations();

  // Helper to handle array conversions (text -> string[])
  const handleArrayChange = (field: keyof AdditionalInfo, value: string) => {
    // Split by newlines only. Blank/whitespace lines are preserved while editing
    // so pressing Enter creates a new line (issue #763); consumers filter empty
    // entries at render time, and the backend drops them on save.
    const items = value.split('\n');
    onChange({
      ...data,
      [field]: items,
    });
  };

  const formatArray = (arr?: string[]) => {
    return arr?.join('\n') || '';
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter') {
      e.stopPropagation();
    }
  };

  return (
    <div className="space-y-6">
      <p className="font-mono text-xs uppercase tracking-wider text-blue-700">
        {t('builder.additionalForm.instructions')}
      </p>

      {/* Extra user-defined blocks. Rendered ABOVE the four fixed fields so
          the "Add block" button + card list stays near the top and doesn't
          require scrolling past the built-in fields to find. */}
      <div className="space-y-2">
        <Label className="font-mono text-xs uppercase tracking-wider text-steel-grey">
          Extra blocks
        </Label>
        <p className="font-mono text-[10px] text-steel-grey">
          Add any additional sub-sections you need (e.g. Publications, Volunteering, Talks). Each
          block gets its own heading and item list — same shape as the four fixed fields below.
        </p>
        <GroupedBlocksEditor
          value={data.extraBlocks}
          onChange={(next) => onChange({ ...data, extraBlocks: next })}
          defaultLabels={['Publications', 'Volunteering', 'Talks', 'Interests', 'Projects']}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {RENAMEABLE_FIELDS.map((f) => (
          <div key={f.field} className="space-y-2">
            <EditableFieldLabel
              htmlFor={f.fieldIdSuffix}
              current={data.labels?.[f.labelKey]}
              defaultLabel={t(f.defaultI18nKey)}
              onCommit={(next) =>
                onChange({
                  ...data,
                  labels: { ...(data.labels ?? {}), [f.labelKey]: next },
                })
              }
              onReset={() => {
                // Reset removes the override so the default heading (from i18n)
                // reappears on the rendered resume.
                if (!data.labels) return;
                const rest = { ...data.labels };
                delete rest[f.labelKey];
                onChange({ ...data, labels: rest });
              }}
            />
            <Textarea
              id={f.fieldIdSuffix}
              value={formatArray(data[f.field] as string[] | undefined)}
              onChange={(e) => handleArrayChange(f.field, e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t(f.placeholderI18nKey)}
              className="min-h-[120px] text-black rounded-none border-black bg-white focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700"
            />
          </div>
        ))}
      </div>
    </div>
  );
};

/**
 * Sub-label with a pencil icon that flips it into an inline text input.
 *   - Not editing: renders the current label (custom override if set,
 *     otherwise the i18n default) with a pencil icon on hover.
 *   - Editing: shows a text input + save (✓) and cancel (×) buttons.
 *   - Enter saves; Escape cancels.
 * If the current label is a custom override, a small "reset" affordance
 * appears next to the pencil so the user can drop back to the default.
 */
interface EditableFieldLabelProps {
  htmlFor: string;
  current: string | undefined; // undefined = no override, use defaultLabel
  defaultLabel: string;
  onCommit: (next: string) => void;
  onReset: () => void;
}

const EditableFieldLabel: React.FC<EditableFieldLabelProps> = ({
  htmlFor,
  current,
  defaultLabel,
  onCommit,
  onReset,
}) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(current ?? defaultLabel);
  const isOverridden = typeof current === 'string' && current.trim().length > 0;
  const shown = isOverridden ? (current as string) : defaultLabel;

  if (editing) {
    return (
      <div className="flex items-center gap-1">
        <input
          type="text"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              onCommit(draft.trim());
              setEditing(false);
            } else if (e.key === 'Escape') {
              setDraft(current ?? defaultLabel);
              setEditing(false);
            }
          }}
          className="flex-1 px-2 py-1 font-mono text-xs uppercase tracking-wider border border-blue-700 bg-white text-black focus:outline-none"
        />
        <button
          type="button"
          onClick={() => {
            onCommit(draft.trim());
            setEditing(false);
          }}
          aria-label="Save label"
          className="p-1 text-blue-700 hover:text-white hover:bg-blue-700 border border-blue-700"
        >
          <Check className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() => {
            setDraft(current ?? defaultLabel);
            setEditing(false);
          }}
          aria-label="Cancel"
          className="p-1 text-steel-grey hover:text-black"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1 group">
      <Label
        htmlFor={htmlFor}
        className="font-mono text-xs uppercase tracking-wider text-steel-grey"
      >
        {shown}
      </Label>
      <button
        type="button"
        onClick={() => {
          setDraft(shown);
          setEditing(true);
        }}
        aria-label={`Rename ${shown}`}
        title="Rename this heading"
        className="p-0.5 text-steel-grey hover:text-blue-700 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <Pencil className="w-3 h-3" />
      </button>
      {isOverridden && (
        <button
          type="button"
          onClick={onReset}
          title="Reset to default"
          className="font-mono text-[9px] uppercase tracking-wider text-steel-grey hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity"
        >
          reset
        </button>
      )}
    </div>
  );
};
