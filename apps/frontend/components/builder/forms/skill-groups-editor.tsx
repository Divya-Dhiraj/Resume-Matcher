'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  parseSkillGroups,
  serializeSkillGroups,
  type SkillGroup,
} from '@/lib/utils/skill-groups';

interface SkillGroupsEditorProps {
  /** The technicalSkills field as stored — a `list[str]` per backend contract. */
  value: string[];
  onChange: (next: string[]) => void;
  /** Placeholder for the fallback raw-text mode. */
  placeholder?: string;
}

const DEFAULT_LABELS = [
  'Programming',
  'Databases',
  'BI & Visualisation',
  'Data Engineering',
  'Cloud',
  'Frameworks & Libraries',
  'Tools & Methods',
];

/**
 * Two-mode editor for the technicalSkills list:
 *   - Grouped: one card per category, label input + comma-separated items input.
 *     This is the default and the whole reason this component exists — a flat
 *     paragraph of skills doesn't parse well for ATS or scan well for a human.
 *   - Raw: exposes the same `list[str]` as newline-separated text for people
 *     who want to hand-edit (or paste from another CV) without the UI in the
 *     way. Both modes read from and write back to the SAME string list, so
 *     switching modes is lossless.
 */
export const SkillGroupsEditor: React.FC<SkillGroupsEditorProps> = ({
  value,
  onChange,
  placeholder,
}) => {
  const [mode, setMode] = useState<'grouped' | 'raw'>('grouped');
  const groups = useMemo<SkillGroup[]>(() => parseSkillGroups(value), [value]);

  const commit = (next: SkillGroup[]) => {
    onChange(serializeSkillGroups(next));
  };

  const updateGroup = (idx: number, patch: Partial<SkillGroup>) => {
    const next = groups.map((g, i) => (i === idx ? { ...g, ...patch } : g));
    commit(next);
  };

  const addGroup = () => {
    // Prefer a category we haven't used yet so the label field lands non-empty.
    const used = new Set(groups.map((g) => g.label.toLowerCase()));
    const nextLabel = DEFAULT_LABELS.find((l) => !used.has(l.toLowerCase())) ?? '';
    commit([...groups, { label: nextLabel, items: [] }]);
  };

  const removeGroup = (idx: number) => {
    commit(groups.filter((_, i) => i !== idx));
  };

  // Serialize a raw textarea value into a normalized items array.
  // Kept as a pure helper so both the blur handler and the mount hydration
  // path use identical splitting rules (comma OR newline, trim, drop empty).
  const parseItemsText = (text: string): string[] =>
    text
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter(Boolean);

  const commitItems = (idx: number, text: string) => {
    updateGroup(idx, { items: parseItemsText(text) });
  };

  if (mode === 'raw') {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase tracking-wider text-steel-grey">
            Raw text — one line per category (Category: item, item, item)
          </span>
          <button
            type="button"
            onClick={() => setMode('grouped')}
            className="font-mono text-[10px] uppercase tracking-wider text-blue-700 hover:underline"
          >
            switch to grouped
          </button>
        </div>
        <Textarea
          value={value.join('\n')}
          onChange={(e) => onChange(e.target.value.split('\n'))}
          placeholder={placeholder}
          className="min-h-[160px] text-black rounded-none border-black bg-white focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700"
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-wider text-steel-grey">
          One category per card — recruiters scan these headings first.
        </span>
        <button
          type="button"
          onClick={() => setMode('raw')}
          className="font-mono text-[10px] uppercase tracking-wider text-blue-700 hover:underline"
        >
          switch to raw
        </button>
      </div>

      {groups.length === 0 && (
        <p className="font-mono text-xs text-steel-grey italic">
          No skill categories yet. Add one to start.
        </p>
      )}

      {groups.map((group, idx) => (
        <SkillGroupCard
          key={idx}
          group={group}
          onLabelChange={(label) => updateGroup(idx, { label })}
          onItemsCommit={(text) => commitItems(idx, text)}
          onRemove={() => removeGroup(idx)}
          idPrefix={`skill-group-${idx}`}
        />
      ))}

      <button
        type="button"
        onClick={addGroup}
        className="inline-flex items-center gap-1 px-3 py-2 font-mono text-xs uppercase tracking-wider border border-black bg-white text-black hover:bg-blue-700 hover:text-white hover:border-blue-700 transition-colors shadow-sw-xs"
      >
        <Plus className="w-3 h-3" />
        Add category
      </button>
    </div>
  );
};

/**
 * One category card. Owns its own draft text state for the skills textarea so
 * typing a comma, a trailing space, or a partial "Python, S" stays on screen
 * while the user keeps typing. We only commit back to the parent (which
 * serializes to the `list[str]` the backend stores) on blur. This is the fix
 * for the "can't type a comma" bug where the parent was eagerly re-parsing on
 * every keystroke, dropping trailing commas and effectively erasing input.
 *
 * When the parent updates the group externally (raw-mode edit, load from DB,
 * add/remove a different card that renumbers indices), we resync the draft
 * ONLY while the field is not focused — resyncing mid-typing would jump the
 * user's caret to the end and lose their in-progress edit.
 */
interface SkillGroupCardProps {
  group: SkillGroup;
  onLabelChange: (label: string) => void;
  onItemsCommit: (text: string) => void;
  onRemove: () => void;
  idPrefix: string;
}

const SkillGroupCard: React.FC<SkillGroupCardProps> = ({
  group,
  onLabelChange,
  onItemsCommit,
  onRemove,
  idPrefix,
}) => {
  const externalItemsText = group.items.join(', ');
  const [itemsDraft, setItemsDraft] = useState(externalItemsText);
  const focusedRef = useRef(false);

  useEffect(() => {
    // Only sync down from parent when the user isn't actively typing here.
    if (!focusedRef.current && externalItemsText !== itemsDraft) {
      setItemsDraft(externalItemsText);
    }
    // itemsDraft intentionally excluded — we watch parent value only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalItemsText]);

  return (
    <div className="border border-black bg-white p-3 space-y-2 shadow-sw-xs">
      <div className="flex items-center gap-2">
        <Label
          htmlFor={`${idPrefix}-label`}
          className="font-mono text-[10px] uppercase tracking-wider text-steel-grey w-16 shrink-0"
        >
          Category
        </Label>
        <input
          id={`${idPrefix}-label`}
          type="text"
          value={group.label}
          onChange={(e) => onLabelChange(e.target.value)}
          placeholder="e.g. Programming"
          className="flex-1 px-2 py-1 font-mono text-xs border border-steel-grey bg-white text-black hover:border-black focus:outline-none focus:border-blue-700"
        />
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${group.label || 'category'}`}
          className="p-1 text-steel-grey hover:text-red-600 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex items-start gap-2">
        <Label
          htmlFor={`${idPrefix}-items`}
          className="font-mono text-[10px] uppercase tracking-wider text-steel-grey w-16 shrink-0 pt-1"
        >
          Skills
        </Label>
        <Textarea
          id={`${idPrefix}-items`}
          value={itemsDraft}
          onChange={(e) => setItemsDraft(e.target.value)}
          onFocus={() => {
            focusedRef.current = true;
          }}
          onBlur={() => {
            focusedRef.current = false;
            // Commit on blur — this normalizes the draft (splits on commas
            // and newlines, trims, drops empties, joins back with ", ")
            // and pushes the tidy list up to the parent.
            onItemsCommit(itemsDraft);
          }}
          placeholder="Comma-separated, e.g. Python, SQL, C#"
          className="flex-1 min-h-[60px] text-xs text-black rounded-none border-steel-grey bg-white focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700"
        />
      </div>
    </div>
  );
};
