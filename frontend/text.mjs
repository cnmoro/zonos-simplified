// Keep each inference well below the server's ~64-second audio budget.
export function splitText(text, limit = 350) {
  const words = text.trim().split(/\s+/u).filter(Boolean);
  const parts = [];
  let current = '';
  for (const word of words) {
    if (current && current.length + word.length + 1 > limit) {
      parts.push(current); current = '';
    }
    current += (current ? ' ' : '') + word;
    if (/[.!?]["”')]*$/u.test(word) && current.length >= limit / 2) {
      parts.push(current); current = '';
    }
  }
  if (current) parts.push(current);
  return parts;
}
