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
]);

export function normalizeScript(text: string) {
  return text.trim().split(/\s+/).filter(Boolean).join(" ");
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

export function transformScript(script: string, style: string) {
  const normalized = normalizeScript(script);
  if (!normalized) {
    return "";
  }

  const openings: Record<string, string> = {
    concise: "핵심부터 말씀드리겠습니다.",
    keynote: "오늘 이 자리에서 우리가 확인할 변화는 분명합니다.",
    persuasive: "여러분께 꼭 설득력 있게 전하고 싶은 점이 있습니다.",
    story: "짧은 장면 하나로 이야기를 시작해보겠습니다.",
  };
  const closings: Record<string, string> = {
    concise: "결론적으로 이 프로젝트는 실시간 피드백을 더 빠르게 만듭니다.",
    keynote: "이 경험이 발표와 면접 준비의 기준을 바꿀 수 있습니다.",
    persuasive: "그래서 지금 이 기능은 충분히 시도할 가치가 있습니다.",
    story: "이제 발표자는 혼자가 아니라, 화면 속 코치와 함께 연습합니다.",
  };

  const opening = openings[style] ?? openings.concise;
  const closing = closings[style] ?? closings.concise;
  return `${opening} ${normalized} ${closing}`;
}

function cleanKeywordToken(token: string) {
  return token.replace(/[^\w가-힣]/g, "");
}

function characterNgrams(text: string) {
  if (text.length <= 2) {
    return new Set([text]);
  }

  const grams = new Set<string>();
  for (let index = 0; index <= text.length - 2; index += 1) {
    grams.add(text.slice(index, index + 2));
  }
  return grams;
}

function attentionSimilarity(left: Set<string>, right: Set<string>) {
  const overlap = [...left].filter((gram) => right.has(gram)).length;
  return overlap / Math.sqrt(Math.max(1, left.size * right.size));
}

export function selectAttentionKeyword(tokens: string[]) {
  const candidates = tokens
    .map((token, sentenceIndex) => ({
      sentenceIndex,
      text: cleanKeywordToken(token),
    }))
    .filter(({ text }) => text.length >= 2 && !keywordStopwords.has(text));

  if (!candidates.length) {
    return null;
  }

  const vectors = candidates.map(({ text }) => characterNgrams(text));
  const scored = candidates.map((candidate, index) => {
    const attention = vectors.reduce((sum, vector, otherIndex) => {
      if (index === otherIndex) {
        return sum;
      }

      return sum + attentionSimilarity(vectors[index], vector);
    }, 0);
    const lengthBonus = Math.min(candidate.text.length / 8, 1);
    const positionBonus = 1 - candidate.sentenceIndex / Math.max(tokens.length, 1) * 0.2;
    return {
      ...candidate,
      score: attention + lengthBonus + positionBonus,
    };
  });

  return scored.sort((left, right) => right.score - left.score)[0]?.text ?? null;
}

export function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}
