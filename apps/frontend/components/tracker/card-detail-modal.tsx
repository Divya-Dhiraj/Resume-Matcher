'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import Pencil from 'lucide-react/dist/esm/icons/pencil';
import Trash2 from 'lucide-react/dist/esm/icons/trash-2';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { useTranslations } from '@/lib/i18n';
import {
  getApplicationDetail,
  updateApplication,
  updateJobContent,
  deleteApplication,
  type ApplicationDetail,
} from '@/lib/api/tracker';

interface CardDetailModalProps {
  applicationId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: () => void;
}

export function CardDetailModal({
  applicationId,
  open,
  onOpenChange,
  onUpdated,
}: CardDetailModalProps) {
  const { t } = useTranslations();
  const router = useRouter();
  const [detail, setDetail] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [notes, setNotes] = useState('');
  const [savingNotes, setSavingNotes] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [editingJd, setEditingJd] = useState(false);
  const [jdDraft, setJdDraft] = useState('');
  const [savingJd, setSavingJd] = useState(false);
  const [jdError, setJdError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !applicationId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    getApplicationDetail(applicationId)
      .then((data) => {
        if (cancelled) return;
        setDetail(data);
        setNotes(data.notes ?? '');
        setNotesError(null);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, applicationId]);

  // Keep textarea Enter from bubbling to dialog/global handlers.
  const handleNotesKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter') e.stopPropagation();
  };

  const handleSaveNotes = async () => {
    if (!applicationId) return;
    setSavingNotes(true);
    setNotesError(null);
    try {
      await updateApplication(applicationId, { notes });
      onUpdated();
    } catch {
      // Show a generic message — never echo raw backend error text inline,
      // which could contain sensitive values.
      setNotesError(t('common.error'));
    } finally {
      setSavingNotes(false);
    }
  };

  const handleStartEditJd = () => {
    setJdDraft(detail?.job_content ?? '');
    setEditingJd(true);
    setJdError(null);
  };

  const handleSaveJd = async () => {
    if (!detail?.job_id || !jdDraft.trim()) return;
    setSavingJd(true);
    setJdError(null);
    try {
      await updateJobContent(detail.job_id, jdDraft.trim());
      setDetail((prev) => (prev ? { ...prev, job_content: jdDraft.trim() } : prev));
      setEditingJd(false);
      onUpdated();
    } catch {
      setJdError(t('common.error'));
    } finally {
      setSavingJd(false);
    }
  };

  const handleDelete = async () => {
    if (!applicationId) return;
    setDeleting(true);
    try {
      await deleteApplication(applicationId);
      onUpdated();
      onOpenChange(false);
    } catch {
      setNotesError(t('common.error'));
    } finally {
      setDeleting(false);
    }
  };

  const resumeAvailable = Boolean(detail?.resume);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{detail?.company || t('tracker.card.companyUnknown')}</DialogTitle>
          <DialogDescription>{detail?.role || t('tracker.card.roleUnknown')}</DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin text-steel-grey" />
          </div>
        ) : detail ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 font-mono text-xs uppercase text-ink-soft">
              <span className="border border-black bg-paper-tint px-2 py-0.5">
                {t(`tracker.columns.${detail.status}`)}
              </span>
              {detail.applied_at && (
                <span>
                  {new Date(detail.applied_at).toLocaleDateString('en-US', {
                    month: 'short',
                    year: 'numeric',
                  })}
                </span>
              )}
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <Label>{t('tracker.modal.jobDescription')}</Label>
                {!editingJd && detail.job_content && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={handleStartEditJd}
                    className="h-6 px-2 font-mono text-xs"
                  >
                    <Pencil className="mr-1 h-3 w-3" />
                    {t('tracker.modal.editJd')}
                  </Button>
                )}
              </div>
              {editingJd ? (
                <>
                  <Textarea
                    value={jdDraft}
                    onChange={(e) => setJdDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.stopPropagation();
                    }}
                    rows={8}
                    className="text-sm"
                  />
                  <div className="flex items-center justify-end gap-2">
                    {jdError && (
                      <span className="font-mono text-xs text-destructive">{jdError}</span>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setEditingJd(false)}
                      disabled={savingJd}
                    >
                      {t('tracker.modal.cancelEditJd')}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleSaveJd}
                      disabled={savingJd || !jdDraft.trim()}
                    >
                      {savingJd ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        t('tracker.modal.saveJd')
                      )}
                    </Button>
                  </div>
                </>
              ) : (
                <div className="max-h-48 overflow-y-auto whitespace-pre-wrap border border-black bg-background p-3 text-sm">
                  {detail.job_content || t('tracker.modal.noJobDescription')}
                </div>
              )}
            </div>

            <div className="space-y-1">
              <Label htmlFor="card-notes">{t('tracker.modal.notes')}</Label>
              <Textarea
                id="card-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                onKeyDown={handleNotesKeyDown}
                placeholder={t('tracker.modal.notesPlaceholder')}
                rows={3}
              />
              <div className="flex items-center justify-end gap-3">
                {notesError && (
                  <span className="font-mono text-xs text-destructive">{notesError}</span>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSaveNotes}
                  disabled={savingNotes}
                >
                  {savingNotes ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    t('tracker.modal.saveNotes')
                  )}
                </Button>
              </div>
            </div>

            {!resumeAvailable && (
              <p className="font-mono text-xs text-warning">
                {t('tracker.modal.resumeUnavailable')}
              </p>
            )}
          </div>
        ) : (
          <p className="py-6 text-center font-mono text-sm text-steel-grey">
            {t('tracker.modal.loadFailed')}
          </p>
        )}

        <DialogFooter className="flex items-center justify-between sm:justify-between">
          <Button
            variant="outline"
            onClick={handleDelete}
            disabled={deleting}
            className="border-destructive text-destructive hover:bg-destructive hover:text-white"
          >
            {deleting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Trash2 className="h-4 w-4" />
                {t('tracker.modal.delete')}
              </>
            )}
          </Button>
          <Button
            onClick={() => {
              if (detail?.resume_id) router.push(`/builder?id=${detail.resume_id}`);
            }}
            disabled={!resumeAvailable}
          >
            <Pencil className="h-4 w-4" />
            {t('tracker.modal.editResume')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
