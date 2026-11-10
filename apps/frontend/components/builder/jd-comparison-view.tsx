'use client';

import { useMemo, useState, useEffect, useCallback } from 'react';
import { type ResumeData } from '@/components/dashboard/resume-component';
import { extractKeywords, calculateMatchStats } from '@/lib/utils/keyword-matcher';
import { JDDisplay } from './jd-display';
import { HighlightedResumeView } from './highlighted-resume-view';
import { reviewResume } from '@/lib/api/resume';
import { CheckCircle, Target, AlertTriangle, Loader2, Zap } from 'lucide-react';
import { useTranslations } from '@/lib/i18n';

interface JDComparisonViewProps {
  jobDescription: string;
  resumeData: ResumeData;
  resumeId: string;
  jobId: string | null;
}

interface ReviewResult {
  match_score: number;
  verdict: string;
  missing_keywords: string[];
  weak_bullets: Array<{
    path?: string;
    text?: string;
    problem?: string;
    fix?: string;
  }>;
  top_3_fixes: string[];
  pass: boolean;
  panel_scores?: Record<string, number>;
  missing_from_resume?: string[];
  fabrication_flags?: string[];
}

export function JDComparisonView({
  jobDescription,
  resumeData,
  resumeId,
  jobId,
}: JDComparisonViewProps) {
  const { t } = useTranslations();

  const [review, setReview] = useState<ReviewResult | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  // Client-side keyword extraction (still used for the highlighted resume view)
  const keywords = useMemo(() => extractKeywords(jobDescription), [jobDescription]);

  const resumeText = useMemo(() => {
    const parts: string[] = [];
    if (resumeData.summary) parts.push(resumeData.summary);
    resumeData.workExperience?.forEach((exp) => {
      if (exp.title) parts.push(exp.title);
      if (exp.company) parts.push(exp.company);
      exp.description?.forEach((d) => parts.push(d));
    });
    resumeData.education?.forEach((edu) => {
      if (edu.degree) parts.push(edu.degree);
      if (edu.institution) parts.push(edu.institution);
    });
    resumeData.personalProjects?.forEach((proj) => {
      if (proj.name) parts.push(proj.name);
      if (proj.role) parts.push(proj.role);
      proj.description?.forEach((d) => parts.push(d));
    });
    if (resumeData.additional) {
      resumeData.additional.technicalSkills?.forEach((s) => parts.push(s));
      resumeData.additional.languages?.forEach((l) => parts.push(l));
      resumeData.additional.certificationsTraining?.forEach((c) => parts.push(c));
    }
    return parts.join(' ');
  }, [resumeData]);

  const stats = useMemo(() => calculateMatchStats(resumeText, keywords), [resumeText, keywords]);

  const runReview = useCallback(async () => {
    if (!jobId) return;
    setReviewLoading(true);
    setReviewError(null);
    try {
      const result = await reviewResume(resumeId, jobId);
      setReview(result);
    } catch (err) {
      setReviewError(err instanceof Error ? err.message : 'Review failed');
    } finally {
      setReviewLoading(false);
    }
  }, [resumeId, jobId]);

  // Auto-run review on mount when jobId is available
  useEffect(() => {
    if (jobId && !review && !reviewLoading) {
      runReview();
    }
  }, [jobId, review, reviewLoading, runReview]);

  const scoreColor = (score: number) =>
    score >= 85 ? 'text-green-700' : score >= 60 ? 'text-yellow-700' : 'text-red-700';

  const scoreBg = (score: number) =>
    score >= 85
      ? 'bg-green-50 border-green-200'
      : score >= 60
        ? 'bg-yellow-50 border-yellow-200'
        : 'bg-red-50 border-red-200';

  return (
    <div className="h-full flex flex-col overflow-auto">
      {/* LLM Review Section */}
      <div className="border-b border-black bg-white">
        {reviewLoading && (
          <div className="flex items-center gap-3 px-6 py-8 justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-primary" />
            <span className="font-mono text-sm">Analyzing resume against JD...</span>
          </div>
        )}

        {reviewError && (
          <div className="px-6 py-4">
            <div className="flex items-center gap-2 text-red-700 mb-2">
              <AlertTriangle className="w-4 h-4" />
              <span className="font-mono text-sm font-bold">Review failed</span>
            </div>
            <p className="font-mono text-xs text-ink-soft">{reviewError}</p>
            <button
              onClick={runReview}
              className="mt-2 border border-black px-3 py-1 font-mono text-xs uppercase hover:bg-ink hover:text-white transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {review && (
          <div className="px-6 py-5">
            {/* Score header */}
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
              <button
                onClick={runReview}
                disabled={reviewLoading}
                className="border border-black px-3 py-1 font-mono text-xs uppercase hover:bg-ink hover:text-white transition-colors disabled:opacity-50"
              >
                Re-analyze
              </button>
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

            {/* Top fixes — these are the improvement hints */}
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

            {/* Missing keywords */}
            {review.missing_keywords && review.missing_keywords.length > 0 && (
              <div className="mb-4">
                <p className="font-mono text-xs font-bold uppercase mb-2">Missing keywords</p>
                <div className="flex flex-wrap gap-1">
                  {review.missing_keywords.map((kw, i) => (
                    <span
                      key={i}
                      className="border border-red-300 bg-red-50 px-2 py-0.5 font-mono text-[10px] text-red-700"
                    >
                      {kw}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Missing from resume */}
            {review.missing_from_resume && review.missing_from_resume.length > 0 && (
              <div className="mb-4">
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

        {!jobId && !reviewLoading && (
          <div className="px-6 py-4">
            <p className="font-mono text-xs text-ink-soft">
              LLM review requires a tailored resume with a linked job. Use the keyword match below.
            </p>
          </div>
        )}
      </div>

      {/* Keyword Stats Bar (client-side) */}
      <div className="flex items-center justify-between px-4 py-3 bg-white border-b border-paper-tint">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Target className="w-4 h-4 text-blue-600" />
            <span className="text-sm font-mono">
              {t('builder.jdMatch.stats.keywordsExtracted', { count: keywords.size })}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-green-600" />
            <span className="text-sm font-mono">
              {t('builder.jdMatch.stats.matchesFound', { count: stats.matchCount })}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-mono text-ink-soft">
            {t('builder.jdMatch.stats.matchRateLabel')}
          </span>
          <span
            className={`text-lg font-bold ${
              stats.matchPercentage >= 50
                ? 'text-green-600'
                : stats.matchPercentage >= 30
                  ? 'text-yellow-600'
                  : 'text-red-600'
            }`}
          >
            {stats.matchPercentage}%
          </span>
        </div>
      </div>

      {/* Split View */}
      <div className="flex-1 grid grid-cols-2 min-h-0">
        {/* Left: JD */}
        <div className="border-r border-paper-tint overflow-hidden">
          <JDDisplay content={jobDescription} />
        </div>

        {/* Right: Resume with highlights */}
        <div className="overflow-hidden">
          <HighlightedResumeView resumeData={resumeData} keywords={keywords} />
        </div>
      </div>
    </div>
  );
}
