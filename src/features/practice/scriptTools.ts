export type ScriptToken = {
  index: number;
  text: string;
  targetStartMs: number;
  targetEndMs: number;
};

export type ScriptPlan = {
  normalizedScript: string;
  syllableCount: number;
  targetSyllablesPerMinute: number;
  estimatedDurationSeconds: number;
  timeline: ScriptToken[];
  warning: string | null;
};

const hangulPattern = /[가-힣]/g;
const tokenPattern = /\S+/g;
const sentenceEndPattern = /[.!?。！？]+$/;
const clauseEndPattern = /[,;:，；：]+$/;
const keywordStopwords = new Set([
  "그리고",
  "그러나",
  "그래서",
  "저는",
  "제가",
  "우리",
  "오늘",
  "안녕하세요",
  "이것",
  "그것",
  "있는",
  "없는",
  "합니다",
  "했습니다",
  "됩니다",
  "입니다",
  "통해",
  "대한",
  "위해",
  "것입니다",
]);
const keywordParticles = [
  "에서",
  "으로",
  "부터",
  "까지",
  "은",
  "는",
  "이",
  "가",
  "을",
  "를",
  "과",
  "와",
  "의",
  "에",
  "로",
  "도",
  "만",
];
const genericEndingPattern = /(겠습니다|습니다|습니다|어요|아요|예요)$/;

export function normalizeScript(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).join(" ");
}

export function scriptSentences(text: string): string[] {
  const sentences: string[] = [];
  let sentence = '';
  for (const token of normalizeScript(text).split(' ').filter(Boolean)) {
    sentence += (sentence ? ' ' : '') + token;
    if (sentenceEndPattern.test(token)) {sentences.push(sentence); sentence = '';}
  }
  if (sentence) sentences.push(sentence);
  return sentences;
}

export type ScriptSummaryGroup = {
  start_sentence: number;
  end_sentence: number;
  original: string;
  hint: string | null;
  error: string | null;
};

export type SummaryProgress = {
  stage: 'preparing' | 'generating' | 'cleaning';
  completed_sentences: number;
  total_sentences: number;
  failed_sentences: number;
};

export type ScriptSummaryResult = {
  normalized_script: string;
  model: string;
  elapsed_seconds: number;
  groups: ScriptSummaryGroup[];
};

export function manualSummaryGroups(script: string): ScriptSummaryGroup[] {
  return scriptSentences(script).map((original, index) => ({start_sentence:index,
    end_sentence:index, original, hint:'', error:null}));
}

export function groupHints(groups: ScriptSummaryGroup[]): Record<number, string> {
  const hints: Record<number, string> = {};
  for (const group of groups) {
    if (!group.hint?.trim()) continue;
    for (let i = group.start_sentence; i <= group.end_sentence; i++) hints[i] = group.hint;
  }
  return hints;
}

export function summaryHints(script: string, result: ScriptSummaryResult): Record<number, string> {
  const originals = scriptSentences(script);
  if (!result || result.normalized_script !== normalizeScript(script)
      || !Array.isArray(result.groups) || !result.groups.length || result.groups.length > originals.length) {
    throw new Error('대본이 변경되었거나 요약 응답이 올바르지 않습니다. 다시 요약해 주세요.');
  }
  let cursor = 0;
  result.groups.forEach(item => {
    if (!item || !Number.isInteger(item.start_sentence) || !Number.isInteger(item.end_sentence)
        || item.start_sentence !== cursor || item.end_sentence < cursor || item.end_sentence >= originals.length
        || item.original !== originals.slice(cursor, item.end_sentence + 1).join(' ')
        || (item.hint !== null && (typeof item.hint !== 'string' || !item.hint.trim() || item.hint.length > 160))
        || (item.error !== null && (typeof item.error !== 'string' || !item.error.trim()))
        || (item.hint === null) !== (item.error !== null)) {
      throw new Error('원문과 요약 문장의 연결을 확인할 수 없습니다. 다시 요약해 주세요.');
    }
    cursor = item.end_sentence + 1;
  });
  if (cursor !== originals.length) throw new Error('요약에서 빠진 원문이 있습니다. 다시 요약해 주세요.');
  return groupHints(result.groups);
}

export function replacementSummaryGroups(script: string, result: ScriptSummaryResult,
  current: ScriptSummaryGroup[]): ScriptSummaryGroup[] {
  summaryHints(script, result);
  if (result.groups.some(group => group.error) && current.some(group => group.hint?.trim())) {
    throw new Error('일부 구간 요약에 실패해 기존 요약을 유지했습니다. 다시 시도하거나 직접 수정하세요.');
  }
  return result.groups;
}

export function appendTranscript(current: string, next: string) {
  const currentText = normalizeScript(current);
  const nextText = normalizeScript(next);
  if (!nextText || currentText.endsWith(nextText)) {
    return currentText;
  }
  if (!currentText || nextText.startsWith(currentText)) {
    return nextText;
  }

  const maxOverlap = Math.min(currentText.length, nextText.length);
  for (let overlap = maxOverlap; overlap > 0; overlap -= 1) {
    if (currentText.endsWith(nextText.slice(0, overlap))) {
      return `${currentText}${nextText.slice(overlap)}`;
    }
  }
  return `${currentText} ${nextText}`;
}

function countSpokenUnits(text: string) {
  const syllables = text.match(hangulPattern)?.length ?? 0;
  return syllables || text.replace(/[^\w]/g, "").length;
}

export function analyzeScript(script: string, timeLimitSeconds: number): ScriptPlan {
  const normalizedScript = normalizeScript(script);
  const tokens = normalizedScript.match(tokenPattern) ?? [];
  const safeLimit = Math.max(30, timeLimitSeconds);
  const syllableCount = countSpokenUnits(normalizedScript);
  const targetSyllablesPerMinute = syllableCount
    ? Math.round((syllableCount * 60 * 10) / safeLimit) / 10
    : 0;

  const weights = tokens.map((token) => {
    let weight = Math.max(1, countSpokenUnits(token));
    if (sentenceEndPattern.test(token)) {
      weight += 4;
    } else if (clauseEndPattern.test(token)) {
      weight += 2;
    }
    return weight;
  });
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0) || 1;
  let cursorMs = 0;
  const timeline = tokens.map((token, index) => {
    const durationMs = Math.round((safeLimit * 1000 * weights[index]) / totalWeight);
    const targetEndMs = index === tokens.length - 1 ? safeLimit * 1000 : cursorMs + durationMs;
    const item = {
      index,
      text: token,
      targetStartMs: cursorMs,
      targetEndMs,
    };
    cursorMs = targetEndMs;
    return item;
  });

  let warning: string | null = null;
  if (targetSyllablesPerMinute > 420) {
    warning = "제한 시간에 비해 대본이 길어 빠르게 읽어야 합니다.";
  } else if (targetSyllablesPerMinute > 0 && targetSyllablesPerMinute < 120) {
    warning = "제한 시간에 비해 대본이 짧아 여유가 많습니다.";
  }

  return {
    normalizedScript,
    syllableCount,
    targetSyllablesPerMinute,
    estimatedDurationSeconds: syllableCount ? Math.round((syllableCount / 300) * 60) : 0,
    timeline,
    warning,
  };
}

function cleanKeywordToken(token: string) {
  let text = token.replace(/[^\w가-힣]/g, "");
  for (const particle of keywordParticles) {
    if (text.length > particle.length + 1 && text.endsWith(particle)) {
      text = text.slice(0, -particle.length);
      break;
    }
  }
  return text;
}

function keywordTokens(text: string) {
  return text
    .split(/\s+/)
    .map(cleanKeywordToken)
    .filter(
      (token) =>
        token.length >= 2 &&
        !keywordStopwords.has(token) &&
        !genericEndingPattern.test(token)
    );
}

export function selectAttentionKeyword(tokens: string[], script = tokens.join(" ")) {
  const candidates = keywordTokens(tokens.join(" "));

  if (!candidates.length) {
    return null;
  }

  const documents = script
    .split(/[.!?。！？]+/)
    .map(keywordTokens)
    .filter((document) => document.length > 0);
  const frequencies = new Map<string, number>();
  for (const candidate of candidates) {
    frequencies.set(candidate, (frequencies.get(candidate) ?? 0) + 1);
  }

  let best = candidates[0];
  let bestScore = -1;
  for (const candidate of new Set(candidates)) {
    const documentFrequency = documents.filter((document) =>
      document.includes(candidate)
    ).length;
    const termFrequency = (frequencies.get(candidate) ?? 0) / candidates.length;
    const inverseDocumentFrequency =
      Math.log((documents.length + 1) / (documentFrequency + 1)) + 1;
    const score = termFrequency * inverseDocumentFrequency;
    if (score > bestScore) {
      best = candidate;
      bestScore = score;
    }
  }
  return best;
}

export function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}
