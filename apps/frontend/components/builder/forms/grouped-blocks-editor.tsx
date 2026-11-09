'use client';

/**
 * GroupedBlocksEditor — reusable editor for any section whose data model is
 * "a list of labeled blocks, each with a free-form item list."
 *
 * Powers two things today:
 *   - New `groupedList` custom sections (added via the "Add New Section"
 *     dialog) — user creates a Publications section, adds blocks for each
 *     year, types papers.
 *   - Extra blocks appended to the built-in Skills & Awards section, when
 *     that wiring is enabled — same UI, different destination on save.
 *
 * Editing rules mirror the SkillGroupsEditor fix from earlier: each block
 * owns a local draft for its items textarea and only commits on blur, so a
 * mid-typing comma or trailing space doesn't get reparsed and dropped.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Pencil, Check, Plus, X } from 'lucide-react';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { GroupedBlock } from '@/components/dashboard/resume-component';

interface GroupedBlocksEditorProps {
  value: GroupedBlock[] | undefined;
  onChange: (next: GroupedBlock[]) => void;
  /** Suggested labels the "Add block" button rotates through by default. */
  defaultLabels?: string[];
  itemsPlaceholder?: string;
}

const DEFAULT_SUGGESTED = ['Technical Skills', 'Languages', 'Certifications', 'Awards'];

let __nextTempId = 1_000_000;
const tempId = () => __nextTempId++;

export const GroupedBlocksEditor: React.FC<GroupedBlocksEditorProps> = ({
  value,
  onChange,
  defaultLabels = DEFAULT_SUGGESTED,
  itemsPlaceholder = 'One per line — or "Category: item, item" for grouped rendering.',
}) => {
  const blocks = value ?? [];

  const commit = (next: GroupedBlock[]) => onChange(next);

  const updateBlock = (idx: number, patch: Partial<GroupedBlock>) =>
    commit(blocks.map((b, i) => (i === idx ? { ...b, ...patch } : b)));

  const removeBlock = (idx: number) => commit(blocks.filter((_, i) => i !== idx));

  const addBlock = () => {
    const used = new Set(blocks.map((b) => b.label.trim().toLowerCase()));
    const suggestion = defaultLabels.find((l) => !used.has(l.toLowerCase())) ?? '';
    commit([...blocks, { id: tempId(), label: suggestion, items: [] }]);
  };

  return (
    <div className="space-y-3">
      {blocks.length === 0 && (
        <p className="font-mono text-xs text-steel-grey italic">No blocks yet. Add one to start.</p>
      )}

      {blocks.map((block, idx) => (
        <GroupedBlockCard
          key={block.id ?? idx}
          block={block}
          idPrefix={`grouped-block-${block.id ?? idx}`}
          itemsPlaceholder={itemsPlaceholder}
          onLabelChange={(label) => updateBlock(idx, { label })}
          onItemsCommit={(items) => updateBlock(idx, { items })}
          onRemove={() => removeBlock(idx)}
        />
      ))}

      <button
        type="button"
        onClick={addBlock}
        className="inline-flex items-center gap-1 px-3 py-2 font-mono text-xs uppercase tracking-wider border border-black bg-white text-black hover:bg-blue-700 hover:text-white hover:border-blue-700 transition-colors shadow-sw-xs"
      >
        <Plus className="w-3 h-3" />
        Add block
      </button>
    </div>
  );
};

/**
 * One block card. Owns its own draft state for the items textarea so typing a
 * comma or trailing space stays visible while the user is still typing; the
 * normalized items[] only flows up to the parent on blur.
 */
interface GroupedBlockCardProps {
  block: GroupedBlock;
  idPrefix: string;
  itemsPlaceholder: string;
  onLabelChange: (label: string) => void;
  onItemsCommit: (items: string[]) => void;
  onRemove: () => void;
}

const GroupedBlockCard: React.FC<GroupedBlockCardProps> = ({
  block,
  idPrefix,
  itemsPlaceholder,
  onLabelChange,
  onItemsCommit,
  onRemove,
}) => {
  const externalItemsText = (block.items ?? []).join('\n');
  const [itemsDraft, setItemsDraft] = useState(externalItemsText);
  const focusedRef = useRef(false);

  useEffect(() => {
    // Only sync down from parent when the user isn't actively typing here —
    // otherwise the caret would jump to the end mid-edit.
    if (!focusedRef.current && externalItemsText !== itemsDraft) {
      setItemsDraft(externalItemsText);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalItemsText]);

  const commitItems = () => {
    // Split on newlines only (matches the existing Additional-form fields).
    // Empty entries are dropped at render time; the raw draft is preserved
    // in state so typing an empty line doesn't disappear mid-edit.
    const items = itemsDraft
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    onItemsCommit(items);
  };

  return (
    <div className="border border-black bg-white p-3 space-y-2 shadow-sw-xs">
      <div className="flex items-center gap-2">
        <Label
          htmlFor={`${idPrefix}-label`}
          className="font-mono text-[10px] uppercase tracking-wider text-steel-grey w-20 shrink-0"
        >
          Heading
        </Label>
        <input
          id={`${idPrefix}-label`}
          type="text"
          value={block.label}
          onChange={(e) => onLabelChange(e.target.value)}
          placeholder="e.g. Technical Skills"
          className="flex-1 px-2 py-1 font-mono text-xs border border-steel-grey bg-white text-black hover:border-black focus:outline-none focus:border-blue-700"
        />
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${block.label || 'block'}`}
          title="Remove this block"
          className="p-1 text-steel-grey hover:text-red-600 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex items-start gap-2">
        <Label
          htmlFor={`${idPrefix}-items`}
          className="font-mono text-[10px] uppercase tracking-wider text-steel-grey w-20 shrink-0 pt-1"
        >
          Items
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
            commitItems();
          }}
          placeholder={itemsPlaceholder}
          className="flex-1 min-h-[80px] text-xs text-black rounded-none border-steel-grey bg-white focus-visible:ring-0 focus-visible:ring-offset-0 focus-visible:border-blue-700"
        />
      </div>
    </div>
  );
};

export default GroupedBlocksEditor;

// Small helper for callers that need to render a Pencil/Check pair alongside
// this editor without pulling lucide-react separately.
export const _icons = { Pencil, Check };
