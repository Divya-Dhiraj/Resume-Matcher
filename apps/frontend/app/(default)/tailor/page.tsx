'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useResumePreview } from '@/components/common/resume_previewer_context';
import type { ImprovedResult } from '@/components/common/resume_previewer_context';
import type { ResumeData } from '@/components/dashboard/resume-component';
import {
  uploadJobDescriptions,
  previewImproveResume,
  confirmImproveResume,
} from '@/lib/api/resume';
import { fetchPromptConfig, type PromptOption } from '@/lib/api/config';
import { getPreviewErrorMessage } from '@/lib/utils/preview-error';
import { Dropdown } from '@/components/ui/dropdown';
import { useStatusCache } from '@/lib/context/status-cache';
import {
  Loader2,
  ArrowLeft,
  AlertTriangle,
  Settings,
  Zap,
  RefreshCw,
  CheckCircle,
  Save,
  FileText,
} from 'lucide-react';
import { useTranslations } from '@/lib/i18n';
import { DiffPreviewModal } from '@/components/tailor/diff-preview-modal';
import { ATSScoreCard } from '@/components/tailor/ats-score-card';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';

type OutputLanguage = 'en' | 'de';

export default function TailorPage() {
  const { t } = useTranslations();
  const [jobDescription, setJobDescription] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [masterResumeId, setMasterResumeId] = useState<string | null>(null);
  const [promptOptions, setPromptOptions] = useState<PromptOption[]>([]);
  const [selectedPromptId, setSelectedPromptId] = useState('keywords');
  const [extrapolationMode, setExtrapolationMode] = useState<'aggressive' | 'conservative'>(
    'aggressive'
  );
  const [outputLanguage, setOutputLanguage] = useState<OutputLanguage>('en');
  const [promptLoading, setPromptLoading] = useState(false);
  const hasUserSelectedPrompt = useRef(false);
  const missingDiffConfirmInFlight = useRef(false);

  // Pipeline result state
  const [pendingResult, setPendingResult] = useState<ImprovedResult | null>(null);
  const [showDiffModal, setShowDiffModal] = useState(false);
  const [diffConfirmError, setDiffConfirmError] = useState<string | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [showRegenerateDialog, setShowRegenerateDialog] = useState(false);
  const [showMissingDiffDialog, setShowMissingDiffDialog] = useState(false);
  const [missingDiffResult, setMissingDiffResult] = useState<ImprovedResult | null>(null);
  const [missingDiffError, setMissingDiffError] = useState<string | null>(null);

  // Re-tailor from keyword chips
  const [confirmedSkills, setConfirmedSkills] = useState<Set<string>>(new Set());
  const [retailorLoading, setRetailorLoading] = useState(false);

  // Track the current job ID for re-tailor
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);

  // Cover letter expand/collapse
  const [coverLetterExpanded, setCoverLetterExpanded] = useState(false);

  // Elapsed timer for long operations
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const startTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    setElapsed(0);
    timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    setElapsed(0);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const router = useRouter();
  const { setImprovedData } = useResumePreview();
  const {
    status: systemStatus,
    isLoading: statusLoading,
    incrementJobs,
    incrementImprovements,
    incrementResumes,
  } = useStatusCache();

  const isLlmConfigured =
    !statusLoading && (systemStatus?.llm_configured || systemStatus?.llm_healthy);

  useEffect(() => {
    const storedId = localStorage.getItem('master_resume_id');
    if (!storedId) {
      router.push('/dashboard');
    } else {
      setMasterResumeId(storedId);
    }
  }, [router]);

  useEffect(() => {
    let cancelled = false;

    const loadPromptConfig = async () => {
      setPromptLoading(true);
      try {
        const config = await fetchPromptConfig();
        if (!cancelled) {
          setPromptOptions(config.prompt_options || []);
          if (!hasUserSelectedPrompt.current) {
            setSelectedPromptId(config.default_prompt_id || 'keywords');
          }
        }
      } catch (err) {
        console.error('Failed to load prompt config', err);
      } finally {
        if (!cancelled) {
          setPromptLoading(false);
        }
      }
    };

    loadPromptConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleTextareaKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter') e.stopPropagation();
  };

  const buildConfirmPayload = (result: ImprovedResult) => {
    if (!masterResumeId) {
      throw new Error('Master resume ID is missing.');
    }
    const resumePreview = result.data.resume_preview;
    if (!resumePreview || typeof resumePreview !== 'object' || Array.isArray(resumePreview)) {
      throw new Error('Resume preview data is invalid.');
    }
    const previewRecord = resumePreview as unknown as Record<string, unknown>;
    if (
      !previewRecord.personalInfo ||
      typeof previewRecord.personalInfo !== 'object' ||
      Array.isArray(previewRecord.personalInfo)
    ) {
      throw new Error('Resume preview data is invalid.');
    }
    return {
      resume_id: masterResumeId,
      job_id: result.data.job_id,
      improved_data: resumePreview as ResumeData,
      improvements:
        result.data.improvements?.map((item) => ({
          suggestion: item.suggestion,
          lineNumber: typeof item.lineNumber === 'number' ? item.lineNumber : null,
        })) ?? [],
    };
  };

  const confirmAndNavigate = async (result: ImprovedResult) => {
    const confirmed = await confirmImproveResume(buildConfirmPayload(result));
    incrementImprovements();
    incrementResumes();
    setImprovedData(confirmed);

    const newResumeId = confirmed?.data?.resume_id;
    if (newResumeId) {
      router.push(`/resumes/${newResumeId}`);
    } else {
      router.push('/builder');
    }
  };

  const getGenerateValidationError = (trimmedDescription: string) => {
    if (!trimmedDescription) return null;
    if (trimmedDescription.length < 50) {
      return t('tailor.errors.jobDescriptionTooShort');
    }
    return null;
  };

  const runGenerate = async (resumeId: string, description: string, skills?: string[]) => {
    try {
      const jobId = currentJobId ?? (await uploadJobDescriptions([description], resumeId));
      if (!currentJobId) {
        incrementJobs();
        setCurrentJobId(jobId);
      }

      const result = await previewImproveResume(
        resumeId,
        jobId,
        selectedPromptId,
        skills,
        extrapolationMode,
        {
          outputLanguage,
          includeCoverLetter: true,
          includeReview: true,
        }
      );

      if (!result?.data?.diff_summary || !result?.data?.detailed_changes) {
        console.warn('Diff data missing for tailor preview; requesting user confirmation.');
        setDiffConfirmError(null);
        setPendingResult(null);
        setShowDiffModal(false);
        setMissingDiffError(null);
        setMissingDiffResult(result);
        setShowMissingDiffDialog(true);
        return;
      }

      setDiffConfirmError(null);
      setMissingDiffError(null);
      setPendingResult(result);
      setConfirmedSkills(new Set());
      setCoverLetterExpanded(false);
      setShowDiffModal(true);
    } catch (err) {
      console.error(err);
      setError(getPreviewErrorMessage(err, t));
    }
  };

  const handleGenerate = async () => {
    const trimmedDescription = jobDescription.trim();
    if (!trimmedDescription || !masterResumeId) return;
    const validationError = getGenerateValidationError(trimmedDescription);
    if (validationError) {
      setError(validationError);
      return;
    }
    setIsLoading(true);
    setError(null);
    setCurrentJobId(null);
    startTimer();
    try {
      await runGenerate(masterResumeId, trimmedDescription);
    } finally {
      setIsLoading(false);
      stopTimer();
    }
  };

  const handleRetailor = async () => {
    if (!masterResumeId || !currentJobId || confirmedSkills.size === 0) return;
    setRetailorLoading(true);
    setError(null);
    startTimer();
    try {
      await runGenerate(masterResumeId, jobDescription.trim(), Array.from(confirmedSkills));
    } finally {
      setRetailorLoading(false);
      stopTimer();
    }
  };

  const toggleSkill = useCallback((skill: string) => {
    setConfirmedSkills((prev) => {
      const next = new Set(prev);
      if (next.has(skill)) next.delete(skill);
      else next.add(skill);
      return next;
    });
  }, []);

  const handleConfirmChanges = async () => {
    if (!pendingResult || isConfirming) return;

    setIsConfirming(true);
    setError(null);
    setDiffConfirmError(null);

    try {
      await confirmAndNavigate(pendingResult);
      setShowDiffModal(false);
      setPendingResult(null);
    } catch (err) {
      console.error(err);
      const errorMessage = t('tailor.errors.failedToConfirm');
      setError(errorMessage);
      setDiffConfirmError(errorMessage);
    } finally {
      setIsConfirming(false);
    }
  };

  const handleRejectChanges = () => {
    setShowDiffModal(false);
    setPendingResult(null);
    setDiffConfirmError(null);
    setShowRegenerateDialog(true);
  };

  const handleCloseDiffModal = () => {
    setShowDiffModal(false);
  };

  const handleCloseMissingDiffDialog = () => {
    setShowMissingDiffDialog(false);
    setMissingDiffResult(null);
    setMissingDiffError(null);
    missingDiffConfirmInFlight.current = false;
  };

  const handleMissingDiffConfirm = async () => {
    if (!missingDiffResult || isLoading || missingDiffConfirmInFlight.current) return;
    missingDiffConfirmInFlight.current = true;
    setIsLoading(true);
    setError(null);
    setMissingDiffError(null);
    try {
      await confirmAndNavigate(missingDiffResult);
      handleCloseMissingDiffDialog();
    } catch (err) {
      console.error(err);
      const errorMessage = t('tailor.errors.failedToConfirm');
      setError(errorMessage);
      setMissingDiffError(errorMessage);
    } finally {
      missingDiffConfirmInFlight.current = false;
      setIsLoading(false);
    }
  };

  const handleRegenerateConfirm = async () => {
    setShowRegenerateDialog(false);
    const trimmedDescription = jobDescription.trim();
    if (!trimmedDescription || !masterResumeId) return;
    const validationError = getGenerateValidationError(trimmedDescription);
    if (validationError) {
      setError(validationError);
      return;
    }
    setIsLoading(true);
    setError(null);
    startTimer();
    try {
      await runGenerate(masterResumeId, trimmedDescription);
    } finally {
      setIsLoading(false);
      stopTimer();
    }
  };

  const review = pendingResult?.data?.review;
  const coverLetter = pendingResult?.data?.cover_letter;

  const scoreColor = (score: number) =>
    score >= 85 ? 'text-green-700' : score >= 60 ? 'text-yellow-700' : 'text-red-700';

  const scoreBg = (score: number) =>
    score >= 85
      ? 'bg-green-50 border-green-200'
      : score >= 60
        ? 'bg-yellow-50 border-yellow-200'
        : 'bg-red-50 border-red-200';

  return (
    <div className="min-h-screen w-full bg-[#F6F5EE] flex flex-col items-center justify-center p-4 md:p-8 font-sans">
      <div className="w-full max-w-4xl bg-white border border-black shadow-sw-lg p-8 md:p-12 lg:p-14 relative">
        {/* Back Button */}
        <Button variant="link" className="absolute top-4 left-4" onClick={() => router.back()}>
          <ArrowLeft className="w-4 h-4" />
          {t('common.back')}
        </Button>

        <div className="mb-8 mt-4 text-center">
          <h1 className="font-serif text-4xl font-bold uppercase tracking-tight mb-2">
            {t('tailor.heroTitle')}
          </h1>
          <p className="font-mono text-sm text-blue-700 font-bold uppercase">
            {'// '}
            {t('tailor.pasteJobDescriptionBelow')}
          </p>
        </div>

        {/* LLM Not Configured Warning */}
        {!statusLoading && !isLlmConfigured && (
          <div className="mb-6 border-2 border-amber-500 bg-amber-50 p-4 shadow-sw-default">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="font-mono text-sm font-bold uppercase tracking-wider text-amber-800">
                  {t('tailor.setupRequiredTitle')}
                </p>
                <p className="font-mono text-xs text-amber-700 mt-1">
                  {t('tailor.noApiKeyMessage')}
                </p>
                <Link
                  href="/settings"
                  className="inline-flex items-center gap-2 mt-3 text-amber-700 hover:text-amber-900 transition-colors"
                >
                  <Settings className="w-4 h-4" />
                  <span className="font-mono text-xs font-bold uppercase underline">
                    {t('tailor.configureApiKey')}
                  </span>
                </Link>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-6">
          <Dropdown
            options={
              promptOptions.length > 0
                ? promptOptions.map((opt) => ({
                    id: opt.id,
                    label: t(`tailor.promptOptions.${opt.id}.label`),
                    description: t(`tailor.promptOptions.${opt.id}.description`),
                  }))
                : [
                    {
                      id: 'nudge',
                      label: t('tailor.promptOptions.nudge.label'),
                      description: t('tailor.promptOptions.nudge.description'),
                    },
                    {
                      id: 'keywords',
                      label: t('tailor.promptOptions.keywords.label'),
                      description: t('tailor.promptOptions.keywords.description'),
                    },
                    {
                      id: 'full',
                      label: t('tailor.promptOptions.full.label'),
                      description: t('tailor.promptOptions.full.description'),
                    },
                  ]
            }
            value={selectedPromptId}
            onChange={(value) => {
              hasUserSelectedPrompt.current = true;
              setSelectedPromptId(value);
            }}
            label={t('tailor.promptLabel')}
            description={t('tailor.promptDescription')}
            disabled={isLoading || promptLoading}
          />

          {/* Extrapolation mode + Language toggle row */}
          <div className="flex flex-wrap items-center gap-4">
            {/* Extrapolation mode */}
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
                  disabled={isLoading}
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
                  disabled={isLoading}
                >
                  Aggressive
                </button>
              </div>
            </div>

            {/* Output language */}
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
                  disabled={isLoading}
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
                  disabled={isLoading}
                >
                  Deutsch
                </button>
              </div>
            </div>
          </div>

          <div className="relative">
            <Textarea
              placeholder={t('tailor.jobDescriptionPlaceholder')}
              className="min-h-[300px] font-mono text-sm bg-background border-2 border-black focus:ring-0 focus:border-blue-700 resize-none p-4 rounded-none"
              value={jobDescription}
              onChange={(e) => setJobDescription(e.target.value)}
              onKeyDown={handleTextareaKeyDown}
              disabled={isLoading}
            />
            <div className="absolute bottom-2 right-2 text-xs font-mono text-steel-grey pointer-events-none">
              {t('tailor.charactersCount', { count: jobDescription.length })}
            </div>
          </div>

          {error && (
            <div className="p-4 bg-red-50 border border-red-200 text-red-700 text-sm font-mono flex items-center gap-2">
              <span>!</span> {error}
            </div>
          )}

          <Button
            size="lg"
            onClick={handleGenerate}
            disabled={isLoading || statusLoading || !jobDescription.trim() || !isLlmConfigured}
            className="w-full"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {t('common.processing')}
                {elapsed > 0 && (
                  <span className="font-mono text-xs opacity-70 ml-2">{elapsed}s</span>
                )}
              </>
            ) : statusLoading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {t('common.checking')}
              </>
            ) : !isLlmConfigured ? (
              t('tailor.configureApiKeyFirst')
            ) : (
              t('tailor.generateTailored')
            )}
          </Button>
        </div>
      </div>

      {/* ============ PIPELINE RESULTS (shown after generation) ============ */}
      {pendingResult && (
        <div className="w-full max-w-4xl mt-6 space-y-6">
          {/* ATS Score Breakdown */}
          {pendingResult.data.ats_score && <ATSScoreCard atsScore={pendingResult.data.ats_score} />}

          {/* JD Match Review — inline */}
          {review && (
            <div className="bg-white border border-black shadow-sw-default p-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div
                    className={`border px-4 py-2 font-mono text-2xl font-bold ${scoreBg(review.match_score)} ${scoreColor(review.match_score)}`}
                  >
                    {review.match_score}/100
                  </div>
                  <div>
                    <p
                      className={`font-mono text-sm font-bold uppercase ${review.verdict === 'INTERVIEW' ? 'text-green-700' : 'text-red-700'}`}
                    >
                      {review.verdict}
                    </p>
                    <p className="font-mono text-xs text-ink-soft">
                      {review.pass ? 'Resume passes all checks' : 'Improvements recommended'}
                    </p>
                  </div>
                </div>
                <span className="font-mono text-xs uppercase text-ink-soft">JD Match Review</span>
              </div>

              {/* Panel scores */}
              {review.panel_scores && (
                <div className="grid grid-cols-4 gap-2 mb-4">
                  {Object.entries(review.panel_scores).map(([name, score]) => (
                    <div key={name} className="border border-paper-tint p-2 bg-white">
                      <p className="font-mono text-[10px] uppercase text-ink-soft truncate">
                        {name.replace('_', ' ')}
                      </p>
                      <p className={`font-mono text-sm font-bold ${scoreColor(score as number)}`}>
                        {score as number}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              {/* Top fixes */}
              {review.top_3_fixes && review.top_3_fixes.length > 0 && (
                <div className="mb-4">
                  <p className="font-mono text-xs font-bold uppercase mb-2 flex items-center gap-1">
                    <Zap className="w-3 h-3" />
                    Top improvements
                  </p>
                  <ol className="list-decimal list-inside space-y-1">
                    {review.top_3_fixes.map((fix, i) => (
                      <li key={i} className="font-serif text-sm text-ink-soft">
                        {fix}
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {/* Missing keywords — selectable chips */}
              {review.missing_keywords && review.missing_keywords.length > 0 && (
                <div className="mb-4">
                  <p className="font-mono text-xs font-bold uppercase mb-2">
                    Missing keywords{' '}
                    <span className="font-normal normal-case text-ink-soft">
                      — click skills you know
                    </span>
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {review.missing_keywords.map((kw, i) => {
                      const isConfirmed = confirmedSkills.has(kw);
                      return (
                        <button
                          key={i}
                          type="button"
                          onClick={() => toggleSkill(kw)}
                          className={`border px-2 py-0.5 font-mono text-[10px] transition-colors cursor-pointer ${
                            isConfirmed
                              ? 'border-green-500 bg-green-50 text-green-700'
                              : 'border-red-300 bg-red-50 text-red-700 hover:border-green-400 hover:bg-green-50/50'
                          }`}
                        >
                          {isConfirmed ? '✓ ' : ''}
                          {kw}
                        </button>
                      );
                    })}
                  </div>
                  {confirmedSkills.size > 0 && (
                    <button
                      onClick={handleRetailor}
                      disabled={retailorLoading || isLoading}
                      className="mt-3 border border-black bg-ink text-white px-4 py-1.5 font-mono text-xs uppercase hover:bg-ink/80 transition-colors disabled:opacity-50 flex items-center gap-2"
                    >
                      {retailorLoading ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <RefreshCw className="w-3 h-3" />
                      )}
                      Re-tailor with {confirmedSkills.size} confirmed skill
                      {confirmedSkills.size !== 1 ? 's' : ''}
                      {elapsed > 0 && retailorLoading && (
                        <span className="opacity-70 ml-1">{elapsed}s</span>
                      )}
                    </button>
                  )}
                </div>
              )}

              {/* Missing from resume */}
              {review.missing_from_resume && review.missing_from_resume.length > 0 && (
                <div>
                  <p className="font-mono text-xs font-bold uppercase mb-2">
                    Not demonstrated in resume
                  </p>
                  <ul className="list-disc list-inside space-y-1">
                    {review.missing_from_resume.map((item, i) => (
                      <li key={i} className="font-serif text-sm text-ink-soft">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Cover Letter Preview */}
          {coverLetter && (
            <div className="bg-white border border-black shadow-sw-default">
              <button
                type="button"
                onClick={() => setCoverLetterExpanded(!coverLetterExpanded)}
                className="w-full flex items-center justify-between px-6 py-4 hover:bg-paper-tint transition-colors"
              >
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4" />
                  <span className="font-mono text-sm font-bold uppercase">Cover Letter</span>
                  <span className="font-mono text-xs text-ink-soft">
                    ({outputLanguage === 'de' ? 'Deutsch' : 'English'})
                  </span>
                </div>
                <span className="font-mono text-xs text-ink-soft">
                  {coverLetterExpanded ? '▲ Collapse' : '▼ Expand'}
                </span>
              </button>
              {coverLetterExpanded && (
                <div className="px-6 pb-6 border-t border-paper-tint">
                  <div className="mt-4 font-serif text-sm whitespace-pre-wrap leading-relaxed">
                    {coverLetter}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Save button — confirms resume + creates tracker entry */}
          <div className="flex gap-3">
            <Button
              size="lg"
              onClick={handleConfirmChanges}
              disabled={isConfirming || isLoading || retailorLoading}
              className="flex-1"
            >
              {isConfirming ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-5 h-5" />
                  Save — Confirm Resume, Cover Letter &amp; Add to Tracker
                </>
              )}
            </Button>
            <Button
              variant="outline"
              size="lg"
              onClick={() => setShowDiffModal(true)}
              disabled={isConfirming || isLoading}
            >
              View Changes
            </Button>
          </div>

          {diffConfirmError && (
            <div className="p-4 bg-red-50 border border-red-200 text-red-700 text-sm font-mono flex items-center gap-2">
              <span>!</span> {diffConfirmError}
            </div>
          )}
        </div>
      )}

      {/* Diff preview modal */}
      {showDiffModal && pendingResult && (
        <DiffPreviewModal
          isOpen={showDiffModal}
          isConfirming={isConfirming}
          onClose={handleCloseDiffModal}
          onReject={handleRejectChanges}
          onConfirm={handleConfirmChanges}
          diffSummary={pendingResult?.data?.diff_summary}
          detailedChanges={pendingResult?.data?.detailed_changes}
          errorMessage={diffConfirmError ?? undefined}
        />
      )}

      <ConfirmDialog
        open={showRegenerateDialog}
        onOpenChange={setShowRegenerateDialog}
        title={t('tailor.regenerateDialog.title')}
        description={t('tailor.regenerateDialog.description')}
        confirmLabel={t('tailor.regenerateDialog.confirmLabel')}
        cancelLabel={t('common.cancel')}
        variant="warning"
        onConfirm={handleRegenerateConfirm}
      />

      <ConfirmDialog
        open={showMissingDiffDialog}
        onOpenChange={(open) => {
          if (!open) {
            handleCloseMissingDiffDialog();
          }
        }}
        title={t('tailor.missingDiffDialog.title')}
        description={t('tailor.missingDiffDialog.description')}
        confirmLabel={t('tailor.missingDiffDialog.confirmLabel')}
        cancelLabel={t('common.cancel')}
        variant="warning"
        closeOnConfirm={false}
        onConfirm={handleMissingDiffConfirm}
        onCancel={handleCloseMissingDiffDialog}
        confirmDisabled={isLoading || !missingDiffResult}
        errorMessage={missingDiffError ?? undefined}
      />
    </div>
  );
}
