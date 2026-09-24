/**
 * Split a beat's narration into what it IS: fact, joke, or modern reference
 * (SPEC.md 8.2 -- facts blue, jokes orange, refs green).
 *
 * The point of the colours is the reviewer's one question at Gate C: "is
 * every blue part something I approved?" So "fact" is claimed only with
 * evidence -- a sentence that shares a number, or at least two content words,
 * with a fact this beat cites. A sentence that merely sits in a fact beat is
 * NOT painted blue on faith; in a beat with facts, whatever is not the fact
 * is the setup's punchline, which is a joke.
 *
 * Sentence-level on purpose. Word-level colouring looks precise and is not:
 * no rule can reliably say which three words of a sentence are the fact.
 */

import type { Fact } from '@/lib/gen/rewind/v1/research_pb';
import type { Proposal } from '@/lib/gen/rewind/v1/relevance_pb';

export type SegmentKind = 'fact' | 'joke' | 'ref' | 'plain';

export interface Segment {
  text: string;
  kind: SegmentKind;
  /** For 'fact': the cited facts it matched, so a tooltip can show sources. */
  facts: Fact[];
}

const SENTENCE = /(?<=[.!?…])\s+/;
const WORD = /[a-z']{4,}/g;
const NUMBER = /\d[\d,.]*/g;

/** Words too common to count as sharing meaning with a fact. */
const STOPWORDS = new Set([
  'about', 'after', 'also', 'been', 'before', 'could', 'every', 'from', 'have', 'here',
  'into', 'just', 'like', 'more', 'most', 'only', 'over', 'some', 'such', 'than', 'that',
  'their', 'them', 'then', 'there', 'these', 'they', 'this', 'those', 'very', 'were',
  'what', 'when', 'which', 'while', 'will', 'with', 'would', 'your',
]);

function words(text: string): Set<string> {
  return new Set(
    (text.toLowerCase().match(WORD) ?? []).filter((w) => !STOPWORDS.has(w)),
  );
}

function numbers(text: string): Set<string> {
  return new Set((text.match(NUMBER) ?? []).map((n) => n.replace(/,/g, '').replace(/\.$/, '')));
}

function matchingFacts(sentence: string, facts: Fact[]): Fact[] {
  const sentenceWords = words(sentence);
  const sentenceNumbers = numbers(sentence);
  return facts.filter((fact) => {
    const source = `${fact.label} ${fact.claim} ${fact.evidence}`;
    const sharedNumber = [...numbers(source)].some((n) => sentenceNumbers.has(n));
    const sharedWords = [...words(source)].filter((w) => sentenceWords.has(w)).length;
    return sharedNumber || sharedWords >= 2;
  });
}

/**
 * @param voice  the beat's narration
 * @param facts  the approved facts THIS beat cites
 * @param refs   the comparisons THIS beat uses
 */
export function highlightBeat(voice: string, facts: Fact[], refs: Proposal[]): Segment[] {
  const sentences = voice.split(SENTENCE).filter((s) => s.trim());
  const names = refs.map((r) => r.reference.toLowerCase()).filter(Boolean);

  return sentences.map((text) => {
    const lower = text.toLowerCase();
    if (names.some((name) => lower.includes(name))) {
      return { text, kind: 'ref', facts: [] };
    }
    const matched = matchingFacts(text, facts);
    if (matched.length > 0) return { text, kind: 'fact', facts: matched };
    return { text, kind: facts.length > 0 ? 'joke' : 'plain', facts: [] };
  });
}
