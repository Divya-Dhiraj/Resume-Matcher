/**
 * Keyword extraction and matching utilities for JD-Resume comparison.
 *
 * Extracts both single-word and multi-word technical phrases from the JD,
 * then checks which ones appear in the resume text.
 */

const STOP_WORDS = new Set([
  // Articles & determiners
  'a',
  'an',
  'the',
  'this',
  'that',
  'these',
  'those',
  // Pronouns
  'i',
  'me',
  'my',
  'myself',
  'we',
  'our',
  'ours',
  'ourselves',
  'you',
  'your',
  'yours',
  'yourself',
  'yourselves',
  'he',
  'him',
  'his',
  'himself',
  'she',
  'her',
  'hers',
  'herself',
  'it',
  'its',
  'itself',
  'they',
  'them',
  'their',
  'theirs',
  'themselves',
  'what',
  'which',
  'who',
  'whom',
  // Common verbs
  'am',
  'is',
  'are',
  'was',
  'were',
  'be',
  'been',
  'being',
  'have',
  'has',
  'had',
  'having',
  'do',
  'does',
  'did',
  'doing',
  'will',
  'would',
  'could',
  'should',
  'might',
  'must',
  'shall',
  'can',
  'need',
  'dare',
  'ought',
  'used',
  // Prepositions & conjunctions
  'and',
  'but',
  'if',
  'or',
  'because',
  'as',
  'until',
  'while',
  'of',
  'at',
  'by',
  'for',
  'with',
  'about',
  'against',
  'between',
  'into',
  'through',
  'during',
  'before',
  'after',
  'above',
  'below',
  'to',
  'from',
  'up',
  'down',
  'in',
  'out',
  'on',
  'off',
  'over',
  'under',
  'again',
  'further',
  'then',
  'once',
  'nor',
  'so',
  'yet',
  'both',
  'either',
  'neither',
  'not',
  'only',
  // Common adverbs & modifiers
  'here',
  'there',
  'when',
  'where',
  'why',
  'how',
  'all',
  'each',
  'every',
  'few',
  'more',
  'most',
  'other',
  'some',
  'such',
  'no',
  'own',
  'same',
  'than',
  'too',
  'very',
  'just',
  'also',
  'now',
  'etc',
  'within',
  'well',
  // Job posting boilerplate — these inflate the denominator without being real skills
  'role',
  'position',
  'job',
  'work',
  'working',
  'team',
  'company',
  'looking',
  'seeking',
  'required',
  'requirements',
  'responsibilities',
  'qualifications',
  'preferred',
  'experience',
  'years',
  'year',
  'ability',
  'skills',
  'knowledge',
  'strong',
  'excellent',
  'good',
  'great',
  'include',
  'including',
  'includes',
  'may',
  'like',
  'e.g',
  'i.e',
  'via',
  // Extended boilerplate — verbs and adjectives common in JDs but not keywords
  'build',
  'maintain',
  'support',
  'develop',
  'help',
  'create',
  'manage',
  'ensure',
  'provide',
  'lead',
  'drive',
  'deliver',
  'implement',
  'design',
  'improve',
  'understand',
  'apply',
  'collaborate',
  'communicate',
  'participate',
  'contribute',
  'identify',
  'define',
  'establish',
  'evaluate',
  'monitor',
  'present',
  'track',
  'use',
  'using',
  'utilize',
  'able',
  'new',
  'key',
  'high',
  'end',
  'based',
  'related',
  'multiple',
  'various',
  'current',
  'relevant',
  'previous',
  'internal',
  'external',
  'across',
  'within',
  'along',
  'fast-paced',
  'environment',
  'effectively',
  'clearly',
  'proactiveness',
  'willingness',
  'solid',
  'practical',
  'foundational',
  'understanding',
  'familiarity',
  'exposure',
  'involvement',
  'comparable',
  'professional',
  'degree',
  'currently',
  'enrolled',
  'field',
  'preferably',
  'final',
  'semesters',
  'proficient',
  'verbal',
  'written',
  'hand',
  'tasks',
  'needs',
  'findings',
  // Generic verbs that appear in JD sentences but aren't real skills
  'give',
  'find',
  'ship',
  'speed',
  'clean',
  'solve',
  'figure',
  'refine',
  'adopt',
  'experiment',
  'query',
  'querying',
  'analyze',
  'applied',
  'features',
  'large',
  'datasets',
  'available',
  'applications',
  'technologies',
  'solutions',
  'concepts',
  'tools',
  'insights',
  'checks',
  'partners',
  'statements',
  'reasoning',
  'productivity',
  'documentation',
  'effectiveness',
  'visibility',
  'actionable',
  'automations',
  'manufacturing',
  'communication',
  'quantitative',
  'frameworks',
  'software',
  'development',
  'monitoring',
  // Web page boilerplate — cookie banners, legal, navigation, footers
  'cookie',
  'cookies',
  'consent',
  'privacy',
  'policy',
  'terms',
  'conditions',
  'legal',
  'notice',
  'website',
  'accept',
  'reject',
  'settings',
  'preferences',
  'browse',
  'browsing',
  'device',
  'browser',
  'personalize',
  'advertising',
  'analytics',
  'performance',
  'functional',
  'essential',
  'transfer',
  'transfers',
  'collect',
  'process',
  'processing',
  'country',
  'countries',
  'located',
  'view',
  'click',
  'page',
  'site',
  'content',
  'information',
  'data',
  'share',
  'shared',
  'third',
  'party',
  'service',
  'services',
  'access',
  'account',
  'sign',
  'login',
  'register',
  'submit',
  'apply',
  'contact',
  'email',
  'phone',
  'address',
  'connect',
  'follow',
  'social',
  'media',
  'copyright',
  'reserved',
  'rights',
  'trademark',
  'program',
  'programs',
  'participate',
  'participates',
  'request',
  'questions',
  'related',
  'accommodations',
  'equal',
  'opportunity',
  'employer',
  'regardless',
  'race',
  'color',
  'religion',
  'gender',
  'identity',
  'national',
  'origin',
  'disability',
  'veteran',
  'status',
  'sexual',
  'orientation',
  'age',
  'protected',
  'improve',
  'analyze',
  // Generic nouns common in both JDs and boilerplate
  'people',
  'person',
  'things',
  'part',
  'time',
  'way',
  'number',
  'day',
  'world',
  'area',
  'areas',
  'place',
  'case',
  'point',
  'group',
  'groups',
  'fact',
  'level',
  'levels',
  'kind',
  'top',
  'priority',
  'important',
  'build',
  'products',
  'business',
  'essential',
  'right',
  'today',
  'update',
  'learn',
  'more',
  // More generic words from JD prose that aren't skills
  'accelerating',
  'actions',
  'asset',
  'attractive',
  'beneficial',
  'bring',
  'category',
  'commit',
  'committed',
  'consideration',
  'desirable',
  'duration',
  'dynamic',
  'expect',
  'factor',
  'founded',
  'free',
  'full',
  'goal',
  'goals',
  'join',
  'logical',
  'manager',
  'manufacture',
  'mark',
  'minimum',
  'model',
  'months',
  'month',
  'multicultural',
  'nice',
  'offer',
  'period',
  'perks',
  'planet',
  'range',
  'receive',
  'recruiter',
  'req',
  'search',
  'starting',
  'start',
  'sustainable',
  'training',
  'transforms',
  'transition',
  'trends',
  'type',
  'wide',
  'willingness',
  'energy',
  'candidates',
  'candidate',
  'expected',
  'daily',
  'line',
  'promote',
  'actively',
  'principles',
  'operating',
  'global',
  'quick',
  'compatible',
  'step',
  'free',
  'expected',
  'uphold',
  // More prose words that inflate keyword count
  'advantageous',
  'analysis',
  'apprentice',
  'attendance',
  'attrition',
  'availability',
  'battery',
  'building',
  'cells',
  'computer',
  'considered',
  'date',
  'dates',
  'december',
  'november',
  'january',
  'february',
  'march',
  'april',
  'june',
  'july',
  'august',
  'september',
  'october',
  'earth',
  'electric',
  'engineering',
  'english',
  'german',
  'french',
  'spanish',
  'everything',
  'extended',
  'intern',
  'internship',
  'location',
  'motors',
  'produce',
  'protecting',
  'science',
  'stakeholders',
  'beneficial',
  'desirable',
  'involvement',
  'exposure',
  'considered',
  'asset',
  'advantage',
  'qualify',
  'qualified',
  'ideal',
  'successful',
  'successful',
  'responsible',
  'describe',
  'described',
  'performs',
  'perform',
  'execution',
  'execute',
  'review',
  'reviewing',
  'reviews',
  'preparing',
  'prepare',
  'prepared',
  'preparing',
  'complex',
  'diverse',
  'innovative',
  'additional',
  'specifically',
  'directly',
  'typically',
  'generally',
  'approximately',
  'assigned',
  'assignment',
  'assignments',
  'complete',
  'completing',
  'completed',
  'demonstrate',
  'demonstrated',
  'required',
  'requires',
  'requiring',
  'necessary',
  'specific',
  'appropriate',
  // Location/geography/company/misc noise
  'batteries',
  'berlin',
  'brandenburg',
  'finished',
  'powered',
  'renewable',
  'roof',
  'solar',
  'vehicles',
  'vehicle',
  'making',
  'problem',
  'problems',
  'decision',
  'decisions',
  'leadership',
  'nheide',
  'gigafactory',
]);

const MIN_WORD_LENGTH = 4;

// Important short technical terms that would be excluded by MIN_WORD_LENGTH
const SHORT_TECH_TERMS = new Set([
  'sql',
  'api',
  'aws',
  'gcp',
  'css',
  'etl',
  'rag',
  'llm',
  'nlp',
  'git',
  'dax',
  'sap',
  'erp',
  'crm',
  'vpc',
  'iam',
  'cdn',
  'dns',
  'ssh',
  'tcp',
  'udp',
  'xml',
  'csv',
  'jwt',
  'orm',
  'npm',
  'k8s',
]);

/**
 * Known multi-word technical terms. If any of these appear in the JD
 * (case-insensitive), they are extracted as a single keyword phrase
 * instead of being split into individual words.
 */
const KNOWN_PHRASES: string[] = [
  // Data & analytics
  'data pipelines',
  'data pipeline',
  'data quality',
  'data engineering',
  'data visualization',
  'data visualizations',
  'data analytics',
  'data analysis',
  'data science',
  'data warehouse',
  'data lake',
  'data modeling',
  'data governance',
  'data integration',
  'big data',
  'data-driven',
  'business intelligence',
  'business analytics',
  'machine learning',
  'deep learning',
  'natural language processing',
  'large language models',
  'large language model',
  // BI tools
  'power bi',
  'google analytics',
  'google sheets',
  // Cloud & infra
  'amazon web services',
  'google cloud',
  'google cloud platform',
  'azure devops',
  'ci cd',
  'ci/cd',
  // Web & frameworks
  'web development',
  'web applications',
  'web application',
  'full stack',
  'front end',
  'back end',
  'front-end',
  'back-end',
  'rest api',
  'rest apis',
  'api design',
  'react native',
  'next.js',
  'node.js',
  'vue.js',
  'angular.js',
  // Databases
  'sql server',
  'mysql',
  'postgresql',
  // DevOps & containers
  'docker compose',
  'kubernetes cluster',
  // Methodologies
  'agile methodology',
  'scrum master',
  'project management',
  'product management',
  'stakeholder management',
  'problem-solving',
  'problem solving',
  // HR / domain-specific
  'hr metrics',
  'hr data',
  'hr analytics',
  // General tech
  'version control',
  'unit testing',
  'integration testing',
  'open source',
  'cross-functional',
  'end-to-end',
  'end to end',
];

// Pre-compute lowercase phrases for matching
const KNOWN_PHRASES_LOWER = KNOWN_PHRASES.map((p) => p.toLowerCase());

/**
 * Strip web-page boilerplate from both ends of scraped JD text.
 *
 * Start cut: skip navigation menus, site headers, "Skip to main content",
 * search bars, etc. — start at the first line that looks like a job title,
 * section header ("What You'll Do"), or metadata ("Job Category", "Req. ID").
 *
 * End cut: stop before benefits, EEO statements, cookie banners, footers.
 */
function stripBoilerplate(text: string): string {
  const lines = text.split('\n');

  // --- Find where the actual JD starts ---
  const startPatterns = [
    /what\s+to\s+expect/i,
    /what\s+you.ll\s+(do|bring)/i,
    /about\s+the\s+(role|position|job|team)/i,
    /job\s+(category|type)\b/i,
    /req\.\s*id/i,
    /location\s*\t/i,
    /responsibilities/i,
    /qualifications/i,
    /overview/i,
  ];
  let startIdx = 0;
  for (let i = 0; i < lines.length; i++) {
    if (startPatterns.some((p) => p.test(lines[i]))) {
      // Back up to include the job title (usually 1-3 lines before metadata)
      startIdx = Math.max(0, i - 3);
      break;
    }
  }

  // --- Find where the JD ends (benefits, EEO, footer) ---
  const endPatterns = [
    /not\s+only\s+do\s+we\s+offer/i,
    /compensation\s+package/i,
    /benefits\s+(include|await|package)/i,
    /equal\s+opportunity\s+employer/i,
    /reasonable\s+accommodations/i,
    /e-verify\s+program/i,
    /help\s+us\s+improve\s+our\s+website/i,
    /we\s+use\s+cookies/i,
    /cookie\s+settings/i,
    /privacy\s+(is\s+a\s+top\s+priority|policy|notice|\s*&\s*legal)/i,
    /©\s*\d{4}/,
    /all\s+rights\s+reserved/i,
    /\bapply\s*$/i,
  ];
  let endIdx = lines.length;
  for (let i = startIdx; i < lines.length; i++) {
    if (endPatterns.some((p) => p.test(lines[i]))) {
      endIdx = i;
      break;
    }
  }

  return lines.slice(startIdx, endIdx).join('\n');
}

/**
 * Extract significant keywords from text.
 * Returns both single-word keywords and multi-word technical phrases.
 */
export function extractKeywords(text: string): Set<string> {
  const keywords = new Set<string>();
  const lowerText = stripBoilerplate(text).toLowerCase();

  // 1. Extract known multi-word phrases first
  const consumedRanges: Array<[number, number]> = [];
  for (const phrase of KNOWN_PHRASES_LOWER) {
    let idx = lowerText.indexOf(phrase);
    while (idx !== -1) {
      keywords.add(phrase);
      consumedRanges.push([idx, idx + phrase.length]);
      idx = lowerText.indexOf(phrase, idx + phrase.length);
    }
  }

  // 2. Extract adjacent bigrams that look technical (both words are non-stop, non-short)
  const wordPattern = /[a-z0-9](?:[a-z0-9-]*[a-z0-9])?/g;
  const wordMatches: Array<{ word: string; start: number; end: number }> = [];
  let m: RegExpExecArray | null;
  while ((m = wordPattern.exec(lowerText)) !== null) {
    wordMatches.push({ word: m[0], start: m.index, end: m.index + m[0].length });
  }

  // Build bigrams from adjacent words (separated only by whitespace/punctuation, max 3 chars gap)
  for (let i = 0; i < wordMatches.length - 1; i++) {
    const a = wordMatches[i];
    const b = wordMatches[i + 1];
    const gap = b.start - a.end;
    if (
      gap <= 3 &&
      a.word.length >= MIN_WORD_LENGTH &&
      b.word.length >= MIN_WORD_LENGTH &&
      !STOP_WORDS.has(a.word) &&
      !STOP_WORDS.has(b.word) &&
      !/^\d+$/.test(a.word) &&
      !/^\d+$/.test(b.word)
    ) {
      const bigram = `${a.word} ${b.word}`;
      // Only add if not already covered by a known phrase
      if (!KNOWN_PHRASES_LOWER.includes(bigram)) {
        // Check if both words are technical-looking (not common English)
        const techBigram = isTechnicalBigram(a.word, b.word);
        if (techBigram) {
          keywords.add(bigram);
        }
      }
    }
  }

  // 3. Extract single words (original behavior, but skip words consumed by phrases)
  for (const { word, start, end } of wordMatches) {
    if (word.length < MIN_WORD_LENGTH && !SHORT_TECH_TERMS.has(word)) continue;
    if (STOP_WORDS.has(word)) continue;
    if (/^\d+$/.test(word)) continue;

    // Skip if this word is fully inside a consumed phrase range
    const insidePhrase = consumedRanges.some(([rs, re]) => start >= rs && end <= re);
    if (insidePhrase) continue;

    keywords.add(word);
  }

  return keywords;
}

/**
 * Heuristic: a bigram is "technical" if at least one word looks like a
 * technology, tool, or domain term (contains digits, hyphens, or is short
 * and capitalized in the original, etc.). We keep it simple: if either
 * word is commonly a modifier in non-technical phrases, skip it.
 */
const BIGRAM_SKIP_WORDS = new Set([
  'also',
  'any',
  'been',
  'being',
  'best',
  'can',
  'could',
  'first',
  'get',
  'got',
  'had',
  'has',
  'have',
  'into',
  'its',
  'just',
  'last',
  'made',
  'make',
  'many',
  'much',
  'one',
  'only',
  'other',
  'over',
  'own',
  'per',
  'set',
  'some',
  'such',
  'take',
  'than',
  'that',
  'the',
  'them',
  'then',
  'these',
  'they',
  'this',
  'those',
  'through',
  'too',
  'two',
  'under',
  'upon',
  'very',
  'was',
  'way',
  'were',
  'what',
  'when',
  'where',
  'while',
  'who',
  'will',
  'would',
  'your',
]);

function isTechnicalBigram(a: string, b: string): boolean {
  if (BIGRAM_SKIP_WORDS.has(a) || BIGRAM_SKIP_WORDS.has(b)) return false;
  // At least one word must contain a digit or hyphen to look technical
  const lookstech = (w: string) => /\d/.test(w) || w.includes('-');
  return lookstech(a) || lookstech(b);
}

/**
 * Split text into segments, marking which segments are keyword matches.
 * Returns an array of { text, isMatch } objects for rendering.
 */
export function segmentTextByKeywords(
  text: string,
  keywords: Set<string>
): Array<{ text: string; isMatch: boolean }> {
  const segments: Array<{ text: string; isMatch: boolean }> = [];

  // Split into word and non-word segments while preserving the original text
  const parts = text.split(/([^a-zA-Z0-9-]+)/);

  for (const part of parts) {
    if (!part) continue;

    const isWord = /^[a-zA-Z0-9-]+$/.test(part);

    if (isWord) {
      const cleanWord = part.toLowerCase().replace(/^-+|-+$/g, '');
      const isMatch = keywords.has(cleanWord);
      segments.push({ text: part, isMatch });
    } else {
      segments.push({ text: part, isMatch: false });
    }
  }

  return segments;
}

/**
 * Calculate match statistics between resume text and JD keywords.
 * Handles both single-word and multi-word phrase matching.
 */
export function calculateMatchStats(
  resumeText: string,
  jdKeywords: Set<string>
): {
  matchedKeywords: Set<string>;
  matchCount: number;
  totalKeywords: number;
  matchPercentage: number;
} {
  const resumeLower = resumeText.toLowerCase();
  const resumeWords = extractKeywords(resumeText);
  const matchedKeywords = new Set<string>();

  for (const keyword of jdKeywords) {
    if (keyword.includes(' ')) {
      // Multi-word phrase: check if it appears as a substring in the resume
      if (resumeLower.includes(keyword)) {
        matchedKeywords.add(keyword);
      }
    } else if (resumeWords.has(keyword)) {
      matchedKeywords.add(keyword);
    }
  }

  const matchCount = matchedKeywords.size;
  const totalKeywords = jdKeywords.size;
  const matchPercentage = totalKeywords > 0 ? Math.round((matchCount / totalKeywords) * 100) : 0;

  return { matchedKeywords, matchCount, totalKeywords, matchPercentage };
}
