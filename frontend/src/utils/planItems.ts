export function extractPlanItems(markdown: string): string[] {
  const lines = markdown.split("\n").map((line) => line.trim()).filter(Boolean);
  const bullets = lines
    .filter((line) => /^([-*]|\d+\.)\s+/.test(line))
    .map((line) => line.replace(/^([-*]|\d+\.)\s+/, "").replace(/^#{1,3}\s+/, "").trim())
    .filter(Boolean);
  if (bullets.length > 0) return bullets.slice(0, 40);
  return lines
    .filter((line) => !/^#{1,3}\s+/.test(line) && !line.startsWith("```"))
    .map((line) => line.replace(/^>\s?/, "").replace(/^#{1,3}\s+/, "").trim())
    .filter(Boolean)
    .slice(0, 40);
}

export function localDateKey(date = new Date()): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}