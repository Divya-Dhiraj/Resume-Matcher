import React from 'react';
import {
  ResumeSingleColumn,
  ResumeTwoColumn,
  ResumeModern,
  ResumeModernTwoColumn,
  ResumeLatex,
  ResumeClean,
  ResumeVivid,
} from '@/components/resume';
import {
  type TemplateSettings,
  type TemplateType,
  DEFAULT_TEMPLATE_SETTINGS,
  settingsToCssVars,
} from '@/lib/types/template-settings';
import baseStyles from '@/components/resume/styles/_base.module.css';

export interface PersonalInfo {
  name?: string;
  title?: string;
  email?: string;
  phone?: string;
  location?: string;
  website?: string;
  linkedin?: string;
  github?: string;
}

export interface Experience {
  id: number;
  title?: string;
  company?: string;
  location?: string;
  years?: string;
  description?: string[];
  descriptionStyles?: ('bullet' | 'plain')[];
}

export interface Education {
  id: number;
  institution?: string;
  degree?: string;
  years?: string;
  description?: string;
}

export interface Project {
  id: number;
  name?: string;
  role?: string;
  years?: string;
  github?: string;
  website?: string;
  description?: string[];
  descriptionStyles?: ('bullet' | 'plain')[];
}

export interface AdditionalInfo {
  technicalSkills?: string[];
  languages?: string[];
  certificationsTraining?: string[];
  awards?: string[];
  // Per-resume overrides for the sub-section headings the templates render
  // inside this section (Technical Skills, Languages, Certifications, Awards).
  // A missing key means "use default from i18n". Wired to backend
  // AdditionalInfo.labels dict; consumed by templates via
  // additionalSectionLabels prop.
  labels?: Partial<AdditionalSectionLabels>;
  // Extra user-defined blocks appended below the four built-in ones —
  // same shape as CustomSection.blocks so the same editor + renderer work.
  // Used to add sub-sections like "Publications" or "Volunteering" INSIDE
  // Skills & Awards without creating a whole new top-level section.
  extraBlocks?: GroupedBlock[];
}

export interface AdditionalSectionLabels {
  technicalSkills: string;
  languages: string;
  certifications: string;
  awards: string;
}

export interface ResumeSectionHeadings {
  summary: string;
  experience: string;
  education: string;
  projects: string;
  certifications: string;
  skills: string;
  languages: string;
  awards: string;
  links: string;
}

export interface ResumeFallbackLabels {
  name: string;
}

// Section Type for dynamic sections
export type SectionType = 'personalInfo' | 'text' | 'itemList' | 'stringList' | 'groupedList';

// One labeled sub-block inside a groupedList section — see CustomSection.blocks.
// Same shape as the built-in Skills & Awards sub-fields, extracted so users
// can build sections that look like it (Publications, Volunteering, …).
export interface GroupedBlock {
  id: number;
  label: string;
  items?: string[];
}

// Section Metadata for dynamic section management
export interface SectionMeta {
  id: string; // Unique identifier (e.g., "summary", "custom_1")
  key: string; // Data key (matches ResumeData field or customSections key)
  displayName: string; // User-visible name
  sectionType: SectionType; // Type of section
  isDefault: boolean; // True for built-in sections
  isVisible: boolean; // Whether to show in resume
  order: number; // Display order (0 = first after personalInfo)
}

// Generic item for custom item-based sections
export interface CustomSectionItem {
  id: number;
  title?: string; // Primary title
  subtitle?: string; // Secondary info (company, institution, etc.)
  location?: string;
  years?: string;
  description?: string[];
  descriptionStyles?: ('bullet' | 'plain')[];
}

// Custom section data container
export interface CustomSection {
  sectionType: SectionType;
  items?: CustomSectionItem[]; // For itemList type
  strings?: string[]; // For stringList type
  text?: string; // For text type
  blocks?: GroupedBlock[]; // For groupedList type
}

export interface ResumeData {
  personalInfo?: PersonalInfo;
  summary?: string;
  workExperience?: Experience[];
  education?: Education[];
  personalProjects?: Project[];
  additional?: AdditionalInfo;
  // NEW: Section metadata and custom sections
  sectionMeta?: SectionMeta[];
  customSections?: Record<string, CustomSection>;
}

interface ResumeProps {
  resumeData: ResumeData;
  template?: TemplateType;
  settings?: TemplateSettings;
  additionalSectionLabels?: Partial<AdditionalSectionLabels>;
  sectionHeadings?: Partial<ResumeSectionHeadings>;
  fallbackLabels?: Partial<ResumeFallbackLabels>;
  /**
   * Content locale ("zh" | "ja" | "ko" | ...). Orders the CJK font fallback
   * stack so a shared codepoint resolves to the right regional face.
   */
  locale?: string;
}

/**
 * Resume Component
 *
 * Main wrapper component that delegates rendering to template-specific components.
 * Applies CSS custom properties from settings for consistent styling.
 *
 * Templates:
 * - swiss-single: Traditional single-column layout (default)
 * - swiss-two-column: Two-column layout with experience sidebar
 * - modern: Single-column with user-selectable accent colors
 * - modern-two-column: Two-column layout with modern colorful accents
 */
const Resume: React.FC<ResumeProps> = ({
  resumeData,
  template = 'swiss-single',
  settings,
  additionalSectionLabels,
  sectionHeadings,
  fallbackLabels,
  locale,
}) => {
  // Merge provided settings with defaults
  const mergedSettings: TemplateSettings = {
    ...DEFAULT_TEMPLATE_SETTINGS,
    ...settings,
    margins: { ...DEFAULT_TEMPLATE_SETTINGS.margins, ...settings?.margins },
    spacing: { ...DEFAULT_TEMPLATE_SETTINGS.spacing, ...settings?.spacing },
    fontSize: { ...DEFAULT_TEMPLATE_SETTINGS.fontSize, ...settings?.fontSize },
  };

  // If template is provided as prop but not in settings, use the prop
  if (template && !settings?.template) {
    mergedSettings.template = template;
  }

  // Convert settings to CSS variables
  const cssVars = settingsToCssVars(mergedSettings, locale);

  // Per-resume label overrides win over anything the caller supplied via the
  // additionalSectionLabels prop (which is normally the i18n defaults). This
  // is how "renamed sub-heading in the editor" reaches the rendered resume.
  const effectiveAdditionalSectionLabels: Partial<AdditionalSectionLabels> = {
    ...additionalSectionLabels,
    ...resumeData.additional?.labels,
  };

  return (
    <div
      className={`${baseStyles['resume-body']} bg-white text-black w-full mx-auto resume-template-${mergedSettings.template}`}
      style={cssVars}
    >
      {mergedSettings.template === 'swiss-single' && (
        <ResumeSingleColumn
          data={resumeData}
          showContactIcons={mergedSettings.showContactIcons}
          additionalSectionLabels={effectiveAdditionalSectionLabels}
        />
      )}
      {mergedSettings.template === 'swiss-two-column' && (
        <ResumeTwoColumn
          data={resumeData}
          showContactIcons={mergedSettings.showContactIcons}
          sectionHeadings={sectionHeadings}
        />
      )}
      {mergedSettings.template === 'modern' && (
        <ResumeModern
          data={resumeData}
          showContactIcons={mergedSettings.showContactIcons}
          additionalSectionLabels={effectiveAdditionalSectionLabels}
        />
      )}
      {mergedSettings.template === 'modern-two-column' && (
        <ResumeModernTwoColumn
          data={resumeData}
          showContactIcons={mergedSettings.showContactIcons}
          sectionHeadings={sectionHeadings}
          fallbackLabels={fallbackLabels}
        />
      )}
      {mergedSettings.template === 'latex' && (
        <ResumeLatex
          data={resumeData}
          showContactIcons={mergedSettings.showContactIcons}
          additionalSectionLabels={effectiveAdditionalSectionLabels}
        />
      )}
      {mergedSettings.template === 'clean' && (
        <ResumeClean
          data={resumeData}
          showContactIcons={mergedSettings.showContactIcons}
          additionalSectionLabels={effectiveAdditionalSectionLabels}
        />
      )}
      {mergedSettings.template === 'vivid' && (
        <ResumeVivid
          data={resumeData}
          showContactIcons={mergedSettings.showContactIcons}
          sectionHeadings={sectionHeadings}
          fallbackLabels={fallbackLabels}
        />
      )}
    </div>
  );
};

export default Resume;
