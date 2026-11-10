'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
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
import type { ImprovedResult } from '@/components/common/resume_previewer_context';

interface ManualAddApplicationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

type TailorPhase = 'idle' | 'creating' | 'uploading-jd' | 'tailoring' | 'confirming' | 'linking';

const PHASE_LABELS: Record<TailorPhase, string> = {
  idle: '',
  creating: 'Creating application…',
  'uploading-jd': 'Uploading job description…',
  tailoring: 'Tailoring your CV to this role…',
  confirming: 'Saving tailored version…',
  linking: 'Linking to application…',
};

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
  const [submitting, setSubmitting] = useState(false);
  const [phase, setPhase] = useState<TailorPhase>('idle');
  const [error, setError] = useState<string | null>(null);

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

  const handleSubmit = useCallback(async () => {
    if (!resumeId || !jobDescription.trim()) {
      setError(t('tracker.manualAdd.validation'));
      return;
    }
    setSubmitting(true);
    setError(null);

    try {
      // 1. Create the application
      setPhase('creating');
      const app = await createApplication({
        resume_id: resumeId,
        job_description: jobDescription.trim(),
        company: company.trim() || undefined,
        role: role.trim() || undefined,
        status,
      });

      // 2. If master resume selected, auto-tailor
      if (selectedIsMaster) {
        try {
          // Upload JD to get a job_id for the improve pipeline
          setPhase('uploading-jd');
          const jobId = await uploadJobDescriptions([jobDescription.trim()], resumeId);

          // Preview the tailored resume
          setPhase('tailoring');
          const preview = await previewImproveResume(resumeId, jobId);

          // Confirm and save the tailored version
          setPhase('confirming');
          const confirmed = await confirmImproveResume(buildConfirmPayload(resumeId, preview));

          const tailoredResumeId = confirmed?.data?.resume_id;
          if (tailoredResumeId) {
            // Link the tailored resume to the application
            setPhase('linking');
            await updateApplication(app.application_id, { resume_id: tailoredResumeId });

            reset();
            onCreated();
            onOpenChange(false);
            router.push(`/resumes/${tailoredResumeId}`);
            return;
          }
        } catch (tailorErr) {
          console.error('Auto-tailor failed, application still created:', tailorErr);
          // Application was created successfully — don't fail the whole operation.
          // Just close and let user tailor manually later.
        }
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
    resumeId,
    jobDescription,
    company,
    role,
    status,
    selectedIsMaster,
    t,
    onCreated,
    onOpenChange,
    router,
  ]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('tracker.manualAdd.title')}</DialogTitle>
          <DialogDescription>{t('tracker.manualAdd.description')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
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

          {phase !== 'idle' && (
            <div className="flex items-center gap-2 border border-black bg-paper-tint p-3">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="font-mono text-xs">{PHASE_LABELS[phase]}</span>
            </div>
          )}

          {error && <p className="font-mono text-xs text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : selectedIsMaster ? (
              'Add & Tailor CV'
            ) : (
              t('tracker.manualAdd.submit')
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
