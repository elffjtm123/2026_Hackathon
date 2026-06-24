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

export function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}
