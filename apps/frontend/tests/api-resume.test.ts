import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { generateInterviewPrep, previewImproveResume } from '@/lib/api/resume';

const interviewPrep = {
  role_fit_analysis: ['Backend API experience fits the role.'],
  resume_questions: [
    {
      question: 'How did you build the API?',
      focus_area: 'Backend architecture',
      suggested_answer_points: ['Discuss resume-grounded API work.'],
    },
  ],
  project_follow_ups: [],
  skill_gaps: [
    {
      skill: 'Kubernetes',
      why_it_matters: 'The JD mentions deployments.',
      preparation_suggestion: 'Review basics without claiming experience.',
    },
  ],
  talking_points: ['Connect API work to the role.'],
};

describe('resume API', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('generates interview prep and parses the structured payload', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          interview_prep: interviewPrep,
          message: 'Interview preparation generated successfully',
        }),
        { status: 200 }
      )
    );

    await expect(generateInterviewPrep('res 123')).resolves.toEqual(interviewPrep);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/resumes/res%20123/generate-interview-prep');
    expect(init.method).toBe('POST');
  });

  it('throws a useful error when interview prep generation fails', async () => {
    fetchMock.mockResolvedValue(new Response('server boom', { status: 500 }));

    await expect(generateInterviewPrep('res-123')).rejects.toThrow(
      'Failed to generate interview preparation'
    );
  });

  it('previewImproveResume sends pipeline options when provided', async () => {
    const mockResult = { data: { request_id: 'r1', resume_preview: {} } };
    fetchMock.mockResolvedValue(new Response(JSON.stringify(mockResult), { status: 200 }));

    await previewImproveResume('res-1', 'job-1', 'keywords', undefined, 'aggressive', {
      outputLanguage: 'de',
      includeCoverLetter: true,
      includeReview: true,
    });

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body);
    expect(body.output_language).toBe('de');
    expect(body.include_cover_letter).toBe(true);
    expect(body.include_review).toBe(true);
  });

  it('previewImproveResume omits pipeline options when not provided', async () => {
    const mockResult = { data: { request_id: 'r1', resume_preview: {} } };
    fetchMock.mockResolvedValue(new Response(JSON.stringify(mockResult), { status: 200 }));

    await previewImproveResume('res-1', 'job-1');

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body);
    expect(body.output_language).toBeUndefined();
    expect(body.include_cover_letter).toBeUndefined();
    expect(body.include_review).toBeUndefined();
  });
});
