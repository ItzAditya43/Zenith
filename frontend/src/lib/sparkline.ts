const BLOCKS = "▁▂▃▄▅▆▇█";

/** Unicode block sparkline, oldest → newest. Missing points render as a gap. */
export function sparkline(values: (number | null)[]): string {
  const nums = values.filter((v): v is number => v != null && Number.isFinite(v));
  if (nums.length === 0) return "";
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  return values
    .map((v) => {
      if (v == null || !Number.isFinite(v)) return " ";
      const i = hi === lo ? 3 : Math.round(((v - lo) / (hi - lo)) * (BLOCKS.length - 1));
      return BLOCKS[i];
    })
    .join("");
}
