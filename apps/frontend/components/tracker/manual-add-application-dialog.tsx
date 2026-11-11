'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down';
import ChevronUp from 'lucide-react/dist/esm/icons/chevron-up';
import RotateCcw from 'lucide-react/dist/esm/icons/rotate-ccw';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Dropdown } from '@/components/ui/dropdown';
import { useTranslations } from '@/lib/i18n';
import {
  fetchResumeList,
  type ResumeListItem,
  uploadJobDescriptions,
  previewImproveResume,
  confirmImproveResume,
} from '@/lib/api/resume';
import { createApplication, updateApplication, type ApplicationStatus } from '@/lib/api/tracker';
import type { ResumeData } from '@/components/dashboard/resume-component';
import type { ImprovedResult, ResumeFieldDiff } from '@/components/common/resume_previewer_context';

interface ManualAddApplicationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

type TailorPhase =
  'idle' | 'uploading-jd' | 'tailoring' | 'retailoring' | 'saving' | 'confirming' | 'linking';

const PHASE_LABELS: Record<TailorPhase, string> = {
  idle: '',
  'uploading-jd': 'Uploading job description…',
  tailoring: 'Tailoring CV + generating cover letter + running JD match…',
  retailoring: 'Re-tailoring with updated keywords…',
  saving: 'Creating application…',
  confirming: 'Saving tailored version…',
  linking: 'Linking to application…',
};

interface ReviewData {
  match_score: number;
  verdict: string;
  missing_keywords: string[];
  pass: boolean;
  panel_scores?: Record<string, number>;
}

export function ManualAddApplicationDialog({
  open,
  onOpenChange,
  onCreated,
}: ManualAddApplicationDialogProps) {
  const { t } = useTranslations();
  const router = useRouter();
  const [resumes, setResumes] = useState<ResumeListItem[]>([]);
  const [resumeId, setResumeId] = useState('');
  const [jobDescription, setJobDescription] = useState('');
  const [company, setCompany] = useState('');
  const [role, setRole] = useState('');
  const [status, setStatus] = useState<ApplicationStatus>('saved');
  const [outputLanguage, setOutputLanguage] = useState<'en' | 'de'>('en');
  const [extrapolationMode, setExtrapolationMode] = useState<'aggressive' | 'conservative'>(
    'aggressive'
  );
  const [submitting, setSubmitting] = useState(false);
  const [phase, setPhase] = useState<TailorPhase>('idle');
  const [error, setError] = useState<string | null>(null);

  // Pipeline results state
  const [previewResult, setPreviewResult] = useState<ImprovedResult | null>(null);
  const [coverLetter, setCoverLetter] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewData | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [coverLetterExpanded, setCoverLetterExpanded] = useState(false);
  const [changesExpanded, setChangesExpanded] = useState(true);
  const [confirmedSkills, setConfirmedSkills] = useState<string[]>([]);

  useEffect(() => {
    if (!open) return;
    fetchResumeList(true)
      .then((items) => {
        setResumes(items);
        const master = items.find((r) => r.is_master);
        if (master) {
          setResumeId(master.resume_id);
        } else if (items.length > 0) {
          setResumeId((prev) => prev || items[0].resume_id);
        }
      })
      .catch(() => setResumes([]));
  }, [open]);

  const selectedIsMaster = resumes.find((r) => r.resume_id === resumeId)?.is_master ?? false;
  const hasResults = previewResult !== null;

  const resumeLabel = (r: ResumeListItem): string => {
    const label = r.title || r.filename || t('tracker.manualAdd.untitledResume');
    return r.is_master ? `${label} ★` : label;
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter') e.stopPropagation();
  };

  const reset = () => {
    setJobDescription('');
    setCompany('');
    setRole('');
    setStatus('saved');
    setError(null);
    setPhase('idle');
    setPreviewResult(null);
    setCoverLetter(null);
    setReview(null);
    setJobId(null);
    setCoverLetterExpanded(false);
    setConfirmedSkills([]);
  };

  const buildConfirmPayload = (masterId: string, result: ImprovedResult) => {
    const resumePreview = result.data.resume_preview;
    if (!resumePreview || typeof resumePreview !== 'object' || Array.isArray(resumePreview)) {
      throw new Error('Resume preview data is invalid.');
    }
    return {
      resume_id: masterId,
      job_id: result.data.job_id,
      improved_data: resumePreview as ResumeData,
      improvements:
        result.data.improvements?.map((item) => ({
          suggestion: item.suggestion,
          lineNumber: typeof item.lineNumber === 'number' ? item.lineNumber : null,
        })) ?? [],
    };
  };

  const runPipeline = useCallback(
    async (skills?: string[], isRetailor?: boolean) => {
      if (!resumeId || !jobDescription.trim()) {
        setError(t('tracker.manualAdd.validation'));
        return;
      }
      setSubmitting(true);
      setError(null);

      try {
        let currentJobId = jobId;

        if (!currentJobId) {
          setPhase('uploading-jd');
          currentJobId = await uploadJobDescriptions([jobDescription.trim()], resumeId);
          setJobId(currentJobId);
        }

        setPhase(isRetailor ? 'retailoring' : 'tailoring');
        const preview = await previewImproveResume(
          resumeId,
          currentJobId,
          undefined,
          skills,
          extrapolationMode,
          {
            outputLanguage,
            includeCoverLetter: true,
            includeReview: true,
          }
        );

        setPreviewResult(preview);
        setCoverLetter(preview.data.cover_letter ?? null);
        if (preview.data.review) {
          setReview(preview.data.review as ReviewData);
        }
      } catch {
        setError('Pipeline failed. Please try again.');
      } finally {
        setSubmitting(false);
        setPhase('idle');
      }
    },
    [resumeId, jobDescription, jobId, extrapolationMode, outputLanguage, t]
  );

  const handleGenerate = useCallback(() => {
    runPipeline();
  }, [runPipeline]);

  const toggleKeyword = useCallback(
    (keyword: string) => {
      const next = confirmedSkills.includes(keyword)
        ? confirmedSkills.filter((k) => k !== keyword)
        : [...confirmedSkills, keyword];
      setConfirmedSkills(next);
      runPipeline(next, true);
    },
    [confirmedSkills, runPipeline]
  );

  const handleSave = useCallback(async () => {
    if (!previewResult) return;
    setSubmitting(true);
    setError(null);

    try {
      setPhase('saving');
      const app = await createApplication({
        resume_id: resumeId,
        job_description: jobDescription.trim(),
        company: company.trim() || undefined,
        role: role.trim() || undefined,
        status,
      });

      setPhase('confirming');
      const confirmed = await confirmImproveResume(buildConfirmPayload(resumeId, previewResult));

      const tailoredResumeId = confirmed?.data?.resume_id;
      if (tailoredResumeId) {
        setPhase('linking');
        await updateApplication(app.application_id, { resume_id: tailoredResumeId });

        reset();
        onCreated();
        onOpenChange(false);
        router.push(`/resumes/${tailoredResumeId}`);
        return;
      }

      reset();
      onCreated();
      onOpenChange(false);
    } catch {
      setError(t('tracker.manualAdd.failed'));
    } finally {
      setSubmitting(false);
      setPhase('idle');
    }
  }, [
    previewResult,
    resumeId,
    jobDescription,
    company,
    role,
    status,
    t,
    onCreated,
    onOpenChange,
    router,
  ]);

  const handleSubmitNonMaster = useCallback(async () => {
    if (!resumeId || !jobDescription.trim()) {
      setError(t('tracker.manualAdd.validation'));
      return;
    }
    setSubmitting(true);
    setError(null);

    try {
      setPhase('saving');
      await createApplication({
        resume_id: resumeId,
        job_description: jobDescription.trim(),
        company: company.trim() || undefined,
        role: role.trim() || undefined,
        status,
      });
      reset();
      onCreated();
      onOpenChange(false);
    } catch {
      setError(t('tracker.manualAdd.failed'));
    } finally {
      setSubmitting(false);
      setPhase('idle');
    }
  }, [resumeId, jobDescription, company, role, status, t, onCreated, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('tracker.manualAdd.title')}</DialogTitle>
          <DialogDescription>{t('tracker.manualAdd.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Form fields — collapsed after generation */}
          {!hasResults && (
            <>
              <div className="space-y-1">
                <Label>{t('tracker.manualAdd.resume')}</Label>
                <Dropdown
                  options={resumes.map((r) => ({ id: r.resume_id, label: resumeLabel(r) }))}
                  value={resumeId}
                  onChange={setResumeId}
                />
                {selectedIsMaster && (
                  <p className="font-mono text-xs text-ink-soft">
                    Master CV selected — your resume will be auto-tailored to the job description.
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <Label htmlFor="manual-jd">{t('tracker.manualAdd.jobDescription')}</Label>
                <Textarea
                  id="manual-jd"
                  value={jobDescription}
                  onChange={(e) => setJobDescription(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={t('tracker.manualAdd.jobDescriptionPlaceholder')}
                  rows={5}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="manual-company">{t('tracker.manualAdd.company')}</Label>
                  <Input
                    id="manual-company"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    placeholder={t('tracker.manualAdd.optional')}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="manual-role">{t('tracker.manualAdd.role')}</Label>
                  <Input
                    id="manual-role"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    placeholder={t('tracker.manualAdd.optional')}
                  />
                </div>
              </div>

              <div className="space-y-1">
                <Label>{t('tracker.manualAdd.status')}</Label>
                <Dropdown
                  options={[
                    { id: 'saved', label: t('tracker.columns.saved') },
                    { id: 'applied', label: t('tracker.columns.applied') },
                  ]}
                  value={status}
                  onChange={(value) => setStatus(value as ApplicationStatus)}
                />
              </div>

              {/* Language & extrapolation mode */}
              {selectedIsMaster && (
                <div className="flex flex-wrap items-center gap-4">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs uppercase text-ink-soft">Language:</span>
                    <div className="flex border border-black">
                      <button
                        type="button"
                        onClick={() => setOutputLanguage('en')}
                        className={`px-3 py-1 font-mono text-xs uppercase transition-colors ${
                          outputLanguage === 'en'
                            ? 'bg-ink text-white'
                            : 'bg-white text-ink hover:bg-paper-tint'
                        }`}
                        disabled={submitting}
                      >
                        English
                      </button>
                      <button
                        type="button"
                        onClick={() => setOutputLanguage('de')}
                        className={`px-3 py-1 font-mono text-xs uppercase border-l border-black transition-colors ${
                          outputLanguage === 'de'
                            ? 'bg-ink text-white'
                            : 'bg-white text-ink hover:bg-paper-tint'
                        }`}
                        disabled={submitting}
                      >
                        Deutsch
                      </button>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs uppercase text-ink-soft">Mode:</span>
                    <div className="flex border border-black">
                      <button
                        type="button"
                        onClick={() => setExtrapolationMode('conservative')}
                        className={`px-3 py-1 font-mono text-xs uppercase transition-colors ${
                          extrapolationMode === 'conservative'
                            ? 'bg-ink text-white'
                            : 'bg-white text-ink hover:bg-paper-tint'
                        }`}
                        disabled={submitting}
                      >
                        Conservative
                      </button>
                      <button
                        type="button"
                        onClick={() => setExtrapolationMode('aggressive')}
                        className={`px-3 py-1 font-mono text-xs uppercase border-l border-black transition-colors ${
                          extrapolationMode === 'aggressive'
                            ? 'bg-ink text-white'
                            : 'bg-white text-ink hover:bg-paper-tint'
                        }`}
                        disabled={submitting}
                      >
                        Aggressive
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Pipeline results — shown after generation */}
          {hasResults && (
            <div className="space-y-4">
              {/* Summary bar */}
              <div className="flex items-center justify-between border border-black bg-paper-tint p-3">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs uppercase text-ink-soft">
                    {company.trim() || 'Application'}
                    {role.trim() ? ` — ${role.trim()}` : ''}
                  </span>
                  <span className="font-mono text-xs uppercase">
                    {outputLanguage === 'de' ? 'DE' : 'EN'} · {extrapolationMode}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setPreviewResult(null);
                    setCoverLetter(null);
                    setReview(null);
                    setJobId(null);
                    setConfirmedSkills([]);
                  }}
                  className="flex items-center gap-1 font-mono text-xs text-primary hover:underline"
                >
                  <RotateCcw className="h-3 w-3" />
                  Edit
                </button>
              </div>

              {/* JD Match scores */}
              {review && (
                <div className="space-y-3 border border-black p-4">
                  <div className="flex items-center justify-between">
                    <span className="font-serif text-sm font-bold uppercase">JD Match</span>
                    <span
                      className={`font-mono text-lg font-bold ${
                        review.match_score >= 80
                          ? 'text-success'
                          : review.match_score >= 60
                            ? 'text-warning'
                            : 'text-destructive'
                      }`}
                    >
                      {review.match_score}%
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <span
                      className={`border px-2 py-0.5 font-mono text-xs uppercase ${
                        review.pass
                          ? 'border-success text-success'
                          : 'border-destructive text-destructive'
                      }`}
                    >
                      {review.verdict}
                    </span>
                  </div>

                  {/* Panel scores */}
                  {review.panel_scores && Object.keys(review.panel_scores).length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(review.panel_scores).map(([panel, score]) => (
                        <div
                          key={panel}
                          className="flex items-center gap-1 border border-black bg-white px-2 py-1"
                        >
                          <span className="font-mono text-xs uppercase text-ink-soft">{panel}</span>
                          <span className="font-mono text-xs font-bold">{score}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Missing keywords as toggleable chips */}
                  {review.missing_keywords && review.missing_keywords.length > 0 && (
                    <div className="space-y-1">
                      <span className="font-mono text-xs uppercase text-ink-soft">
                        Missing keywords — click to add and re-tailor:
                      </span>
                      <div className="flex flex-wrap gap-1">
                        {review.missing_keywords.map((kw) => {
                          const selected = confirmedSkills.includes(kw);
                          return (
                            <button
                              key={kw}
                              type="button"
                              onClick={() => toggleKeyword(kw)}
                              disabled={submitting}
                              className={`border px-2 py-0.5 font-mono text-xs transition-colors ${
                                selected
                                  ? 'border-primary bg-primary text-white'
                                  : 'border-black bg-white text-ink hover:bg-paper-tint'
                              }`}
                            >
                              {kw}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Cover letter */}
              {coverLetter && (
                <div className="border border-black">
                  <button
                    type="button"
                    onClick={() => setCoverLetterExpanded(!coverLetterExpanded)}
                    className="flex w-full items-center justify-between p-3 hover:bg-paper-tint"
                  >
                    <span className="font-serif text-sm font-bold uppercase">Cover Letter</span>
                    {coverLetterExpanded ? (
                      <ChevronUp className="h-4 w-4" />
                    ) : (
                      <ChevronDown className="h-4 w-4" />
                    )}
                  </button>
                  {coverLetterExpanded && (
                    <div className="border-t border-black p-4">
                      <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                        {coverLetter}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {/* Detailed changes with diff highlighting */}
              {previewResult?.data.detailed_changes &&
                previewResult.data.detailed_changes.length > 0 && (
                  <div className="border border-black">
                    <button
                      type="button"
                      onClick={() => setChangesExpanded(!changesExpanded)}
                      className="flex w-full items-center justify-between p-3 hover:bg-paper-tint"
                    >
                      <span className="font-serif text-sm font-bold uppercase">
                        Changes ({previewResult.data.detailed_changes.length})
                      </span>
                      {changesExpanded ? (
                        <ChevronUp className="h-4 w-4" />
                      ) : (
                        <ChevronDown className="h-4 w-4" />
                      )}
                    </button>
                    {changesExpanded && (
                      <div className="border-t border-black divide-y divide-black/10">
                        {(previewResult.data.detailed_changes as ResumeFieldDiff[]).map(
                          (change, i) => (
                            <div key={i} className="p-3 space-y-1">
                              <div className="flex items-center gap-2">
                                <span
                                  className={`px-1.5 py-0.5 font-mono text-[10px] uppercase ${
                                    change.change_type === 'added'
                                      ? 'bg-success/10 text-success'
                                      : change.change_type === 'removed'
                                        ? 'bg-destructive/10 text-destructive'
                                        : 'bg-primary/10 text-primary'
                                  }`}
                                >
                                  {change.change_type}
                                </span>
                                <span className="font-mono text-[10px] text-ink-soft uppercase">
                                  {change.field_path}
                                </span>
                              </div>
                              {change.original_value && (
                                <p className="font-sans text-xs text-ink-soft line-through decoration-destructive/40">
                                  {change.original_value}
                                </p>
                              )}
                              {change.new_value && (
                                <p className="font-sans text-xs bg-success/5 border-l-2 border-success pl-2">
                                  {change.new_value}
                                </p>
                              )}
                            </div>
                          )
                        )}
                      </div>
                    )}
                  </div>
                )}

              {/* Fallback: plain improvements if no detailed_changes */}
              {previewResult?.data.improvements &&
                previewResult.data.improvements.length > 0 &&
                (!previewResult.data.detailed_changes ||
                  previewResult.data.detailed_changes.length === 0) && (
                  <div className="border border-black p-4">
                    <span className="font-serif text-sm font-bold uppercase">
                      Changes Made ({previewResult.data.improvements.length})
                    </span>
                    <ul className="mt-2 space-y-1">
                      {previewResult.data.improvements.map((imp, i) => (
                        <li key={i} className="font-mono text-xs text-ink-soft">
                          • {imp.suggestion}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
            </div>
          )}

          {/* Phase indicator */}
          {phase !== 'idle' && (
            <div className="flex items-center gap-2 border border-black bg-paper-tint p-3">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="font-mono text-xs">{PHASE_LABELS[phase]}</span>
            </div>
          )}

          {error && <p className="font-mono text-xs text-destructive">{error}</p>}
        </div>

        <DialogFooter className="gap-2">
          {selectedIsMaster && !hasResults && (
            <Button onClick={handleGenerate} disabled={submitting || !jobDescription.trim()}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Generate'}
            </Button>
          )}
          {selectedIsMaster && hasResults && (
            <Button onClick={handleSave} disabled={submitting}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                'Save — Confirm Resume, Cover Letter & Add to Tracker'
              )}
            </Button>
          )}
          {!selectedIsMaster && (
            <Button onClick={handleSubmitNonMaster} disabled={submitting}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                t('tracker.manualAdd.submit')
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
