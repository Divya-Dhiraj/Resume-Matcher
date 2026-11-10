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
  'report',
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
]);

const MIN_WORD_LENGTH = 3;

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
 * Extract significant keywords from text.
 * Returns both single-word keywords and multi-word technical phrases.
 */
export function extractKeywords(text: string): Set<string> {
  const keywords = new Set<string>();
  const lowerText = text.toLowerCase();

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
    if (word.length < MIN_WORD_LENGTH) continue;
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
