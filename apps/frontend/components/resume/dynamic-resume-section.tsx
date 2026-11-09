import React from 'react';
import type {
  ResumeData,
  SectionMeta,
  CustomSection,
  CustomSectionItem,
  GroupedBlock,
} from '@/components/dashboard/resume-component';
import { formatDateRange } from '@/lib/utils';
import { DescriptionList } from './description-list';
import { GroupedSkillsList } from './grouped-skills-list';
import baseStyles from './styles/_base.module.css';

interface DynamicResumeSectionProps {
  sectionMeta: SectionMeta;
  resumeData: ResumeData;
}

/**
 * DynamicResumeSection Component
 *
 * Renders custom sections in resume templates based on section type.
 * Uses the same CSS classes as built-in sections for consistent styling.
 */
export const DynamicResumeSection: React.FC<DynamicResumeSectionProps> = ({
  sectionMeta,
  resumeData,
}) => {
  // Get the custom section data
  const customSection = resumeData.customSections?.[sectionMeta.key];

  if (!customSection) return null;

  // Check if section has content
  const hasContent = (() => {
    switch (sectionMeta.sectionType) {
      case 'text':
        return Boolean(customSection.text?.trim());
      case 'itemList':
        return Boolean(customSection.items?.length);
      case 'stringList':
        return Boolean(customSection.strings?.length);
      case 'groupedList':
        // Any block at all keeps the section visible so the user sees their
        // new section's title in the live preview immediately after they
        // add it — the alternative (require populated content) hides the
        // section entirely until it has something in it, which reads as
        // "the section didn't get created." Empty blocks are skipped inside
        // GroupedListSectionContent, so the heading appears with no inner
        // rows until the user types something.
        return (customSection.blocks?.length ?? 0) > 0;
      default:
        return false;
    }
  })();

  if (!hasContent) return null;

  return (
    <div className={baseStyles['resume-section']}>
      <h3 className={baseStyles['resume-section-title']}>{sectionMeta.displayName}</h3>
      {renderContent(sectionMeta.sectionType, customSection)}
    </div>
  );
};

/**
 * Render section content based on type
 */
function renderContent(sectionType: SectionMeta['sectionType'], customSection: CustomSection) {
  switch (sectionType) {
    case 'text':
      return <TextSectionContent text={customSection.text || ''} />;
    case 'itemList':
      return <ItemListSectionContent items={customSection.items || []} />;
    case 'stringList':
      return <StringListSectionContent strings={customSection.strings || []} />;
    case 'groupedList':
      return <GroupedListSectionContent blocks={customSection.blocks || []} />;
    default:
      return null;
  }
}

/**
 * Text Section Content (like Summary)
 */
const TextSectionContent: React.FC<{ text: string }> = ({ text }) => {
  if (!text.trim()) return null;

  return <p className={`text-justify ${baseStyles['resume-text']}`}>{text}</p>;
};

/**
 * Item List Section Content (like Experience)
 */
const ItemListSectionContent: React.FC<{ items: CustomSectionItem[] }> = ({ items }) => {
  if (items.length === 0) return null;

  return (
    <div className={baseStyles['resume-items']}>
      {items.map((item) => (
        <div key={item.id} className={baseStyles['resume-item']}>
          {/* Title and Years Row */}
          <div className={`flex justify-between items-baseline ${baseStyles['resume-row-tight']}`}>
            <h4 className={baseStyles['resume-item-title']}>{item.title}</h4>
            {item.years && (
              <span className={`${baseStyles['resume-meta-sm']} shrink-0 ml-4`}>
                {formatDateRange(item.years)}
              </span>
            )}
          </div>

          {/* Subtitle and Location Row */}
          {(item.subtitle || item.location) && (
            <div
              className={`flex justify-between items-center ${baseStyles['resume-row']} ${baseStyles['resume-item-subtitle']}`}
            >
              {item.subtitle && <span>{item.subtitle}</span>}
              {item.location && <span>{item.location}</span>}
            </div>
          )}

          {/* Description Points */}
          <DescriptionList items={item.description} styles={item.descriptionStyles} />
        </div>
      ))}
    </div>
  );
};

/**
 * String List Section Content (like Skills)
 */
const StringListSectionContent: React.FC<{ strings: string[] }> = ({ strings }) => {
  if (strings.length === 0) return null;
  // Route through the shared grouped renderer so a stringList entry that
  // happens to be in the "Category: item, item" shape still bolds the
  // category — same behavior as the built-in Skills field.
  return (
    <div className={baseStyles['resume-text-sm']}>
      <GroupedSkillsList skills={strings} layout="inline" className="flex flex-col gap-0.5" />
    </div>
  );
};

/**
 * Grouped List Section Content — multiple labeled sub-blocks, each a mini
 * string list. Renders like the built-in Skills & Awards, with each block's
 * label bolded above its comma-joined items (grouped-skill "Category: item"
 * lines still render as inner bold groups via GroupedSkillsList).
 */
const GroupedListSectionContent: React.FC<{ blocks: GroupedBlock[] }> = ({ blocks }) => {
  const nonEmpty = blocks.filter((b) => b.label?.trim() || (b.items?.length ?? 0) > 0);
  if (nonEmpty.length === 0) return null;

  return (
    <div className={`${baseStyles['resume-stack']} ${baseStyles['resume-text-sm']}`}>
      {nonEmpty.map((block, idx) => (
        <div key={block.id ?? idx} className="flex">
          <span className="font-bold w-32 shrink-0">
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
    </div>
  );
};

export default DynamicResumeSection;
