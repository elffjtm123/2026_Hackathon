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
