/** 用户可见额度单位：陪伴点。账本仍为分钟，1 分钟 = 10 陪伴点。 */
export const POINTS_PER_MINUTE = 10;

export function minutesToPoints(minutes: number | null | undefined): number | null {
  if (minutes == null || Number.isNaN(Number(minutes))) return null;
  const m = Number(minutes);
  if (m <= 0) return 0;
  const points = Math.round(m * POINTS_PER_MINUTE);
  return points > 0 ? points : 1;
}

export function formatPointsLabel(
  minutes: number | null | undefined,
  opts?: { suffix?: string; empty?: string }
): string {
  const points = minutesToPoints(minutes);
  if (points == null) return opts?.empty ?? "—";
  const suffix = opts?.suffix ?? "陪伴点";
  return `${points} ${suffix}`;
}

/** 将套餐描述里的「N分钟」粗略换成陪伴点；已是陪伴点则原样返回。 */
export function describePlanForUser(
  description: string | null | undefined,
  durationMinutes?: number | null
): string {
  const raw = String(description || "").trim();
  if (raw.includes("陪伴点")) return raw;
  if (durationMinutes != null && Number(durationMinutes) > 0) {
    const pts = minutesToPoints(Number(durationMinutes));
    if (pts != null) {
      if (/分钟\s*\/\s*月/.test(raw) || raw.endsWith("分钟/月")) {
        return `含 ${pts} 陪伴点/月`;
      }
      if (/分钟/.test(raw) || !raw) {
        return `含 ${pts} 陪伴点`;
      }
    }
  }
  return raw.replace(/(\d+(?:\.\d+)?)\s*分钟(?:\s*\/\s*月)?/g, (_m, n) => {
    const pts = minutesToPoints(Number(n));
    return pts == null ? _m : `${pts} 陪伴点`;
  });
}
