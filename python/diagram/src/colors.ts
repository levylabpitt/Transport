// The table's group colors (expconfig/palette.py), so both views match.
export const FILL = {
  device: "#fcf0c8",
  measurement: "#eadef8",
  kh: "#ceeeda",
  lockin: "#d4e0fc",
  other: "#fcdecc",
};

// Warm hues only (red, orange, yellow, pink, purple), so a pad never looks like an
// instrument; one color per electrode name, so a teed pad repeats it.
const HUES = [0, 18, 32, 46, 56, 275, 295, 315, 335];

export function electrodeColor(name: string, muted = false): string {
  let h = 2166136261;
  for (const c of name) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
  return muted ? `hsl(${HUES[h % HUES.length]} 45% 92%)` : `hsl(${HUES[h % HUES.length]} 80% 84%)`;
}
