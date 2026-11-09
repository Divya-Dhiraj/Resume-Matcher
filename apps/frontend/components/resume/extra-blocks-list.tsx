import React from 'react';
import type { GroupedBlock } from '@/components/dashboard/resume-component';
import { GroupedSkillsList } from './grouped-skills-list';

interface ExtraBlocksListProps {
  blocks: GroupedBlock[] | undefined;
  /**
   * Width class for the label column when layout is two-column.
   * Matches the built-in Skills & Awards field labels so the extra blocks
   * line up cleanly with Technical Skills / Languages / etc.
   */
  labelWidthClass?: string;
  /** Match the surrounding text sizing. */
  className?: string;
}

/**
 * Renders `additional.extraBlocks` — the user-defined sub-blocks the editor
 * appends below the four built-in Skills & Awards fields. Same visual
 * treatment as those fields: bold label column + inline items with
 * category-splitting via GroupedSkillsList.
 *
 * Kept template-agnostic so every template (single-column, modern, clean,
 * latex, two-column pill layouts, vivid sidebar) can drop it in with a
 * one-liner and pass template-specific class overrides.
 */
export const ExtraBlocksList: React.FC<ExtraBlocksListProps> = ({
  blocks,
  labelWidthClass = 'w-32',
  className,
}) => {
  const nonEmpty = (blocks ?? []).filter((b) => b.label?.trim() || (b.items?.length ?? 0) > 0);
  if (nonEmpty.length === 0) return null;

  return (
    <>
      {nonEmpty.map((block, idx) => (
        <div key={block.id ?? idx} className={className ?? 'flex'}>
          <span className={`font-bold shrink-0 ${labelWidthClass}`}>
            {block.label?.trim() || ''}
            {block.label?.trim() ? ':' : ''}
          </span>
          <div className="flex-1">
            <GroupedSkillsList
              skills={block.items ?? []}
              layout="inline"
              className="flex flex-col gap-0.5"
            />
          </div>
        </div>
      ))}
    </>
  );
};

export default ExtraBlocksList;
