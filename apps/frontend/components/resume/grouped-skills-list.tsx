import React from 'react';
import { parseSkillGroups } from '@/lib/utils/skill-groups';

interface GroupedSkillsListProps {
  /** The raw technicalSkills strings as stored on the backend. */
  skills: string[];
  /**
   * How each row is arranged:
   *   - `two-column` (default): fixed-width bold label column + skills column.
   *     Best for full-width single-column templates — each category lines up
   *     under the last one, and an ATS row-reader picks up `Label: items`
   *     cleanly.
   *   - `inline`: label and items on one flowing line, best for narrow sidebars.
   *   - `stack`: label on its own line, items below. Best for very narrow columns.
   * A bare (unlabeled) group renders items only.
   */
  layout?: 'two-column' | 'inline' | 'stack';
  /** Optional className applied to the wrapping list, for grid gap control. */
  className?: string;
  /** Width class for the label column when `layout="two-column"`. */
  labelWidthClass?: string;
  /** Optional joiner between items — defaults to ", ". */
  joiner?: string;
}

/**
 * Renders the flat `technicalSkills: string[]` as visually distinct groups.
 * Each stored string in the shape `"Category: item, item"` becomes one row
 * with the category bolded; a string without a `:` renders as a bare skill in
 * an unnamed trailing bucket. The whole system round-trips: the editor writes
 * the same shape this component reads, so what the user types is what the
 * resume shows, and both stay one `list[str]` for the backend.
 */
export const GroupedSkillsList: React.FC<GroupedSkillsListProps> = ({
  skills,
  layout = 'two-column',
  className,
  labelWidthClass = 'w-40',
  joiner = ', ',
}) => {
  const groups = parseSkillGroups(skills);
  if (groups.length === 0) return null;

  return (
    <div className={className ?? 'flex flex-col gap-0.5'}>
      {groups.map((group, idx) => {
        const items = group.items.filter(Boolean).join(joiner);
        if (!group.label) {
          return (
            <div key={idx} className={layout === 'inline' ? 'inline' : 'block'}>
              {items}
            </div>
          );
        }
        if (layout === 'stack') {
          return (
            <div key={idx}>
              <div className="font-bold">{group.label}</div>
              <div>{items}</div>
            </div>
          );
        }
        if (layout === 'inline') {
          return (
            <div key={idx}>
              <span className="font-bold">{group.label}: </span>
              <span>{items}</span>
            </div>
          );
        }
        return (
          <div key={idx} className="flex">
            <span className={`font-bold shrink-0 ${labelWidthClass}`}>{group.label}:</span>
            <span className="flex-1">{items}</span>
          </div>
        );
      })}
    </div>
  );
};

export default GroupedSkillsList;
