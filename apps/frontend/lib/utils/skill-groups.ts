/**
 * Skill group encoding — shared by the editor form (parse for edit, format for
 * save) and the resume templates (parse to render category headers).
 *
 * technicalSkills stays a `list[str]` on the backend for full backward
 * compatibility with the improver / refiner / ATS / DB layer; a grouped skill
 * is encoded as one string per category in the shape
 *
 *   "BI & Visualisation: Power BI, Tableau, QuickSight"
 *
 * A string without a `:` is treated as a bare ungrouped skill (parked into an
 * unnamed group so we don't drop it during round-trips).
 */

export interface SkillGroup {
  /** Category name — "" for the fallback ungrouped bucket. */
  label: string;
  items: string[];
}

/**
 * Split a comma-separated skill list while respecting bracketed regions, so
 * `"SQL (window functions, CTEs), Python"` stays two skills, not four.
 */
export function splitInlineSkills(rest: string): string[] {
  const items: string[] = [];
  let buf = '';
  let depth = 0;
  for (const ch of rest) {
    if (ch === '(' || ch === '[' || ch === '{') {
      depth += 1;
      buf += ch;
    } else if (ch === ')' || ch === ']' || ch === '}') {
      depth = Math.max(0, depth - 1);
      buf += ch;
    } else if (ch === ',' && depth === 0) {
      const tok = buf.trim();
      if (tok) items.push(tok);
      buf = '';
    } else {
      buf += ch;
    }
  }
  const tail = buf.trim();
  if (tail) items.push(tail);
  return items;
}

/**
 * Parse one saved technicalSkills string. Returns null for empty input.
 * A leading label + `:` yields a labeled group; anything else becomes a
 * single-item unnamed bucket, which the caller can merge with siblings.
 */
export function parseSkillLine(line: string): SkillGroup | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  const colonIdx = trimmed.indexOf(':');
  if (colonIdx <= 0) {
    return { label: '', items: [trimmed] };
  }
  const label = trimmed.slice(0, colonIdx).trim();
  const rest = trimmed.slice(colonIdx + 1).trim();
  if (!label) return { label: '', items: [trimmed] };
  return { label, items: rest ? splitInlineSkills(rest) : [] };
}

/**
 * Read the whole technicalSkills array into groups. Consecutive bare skills
 * collapse into one unnamed group at the end so the editor doesn't render one
 * card per bare skill.
 */
export function parseSkillGroups(lines: string[] | undefined): SkillGroup[] {
  if (!lines || lines.length === 0) return [];
  const groups: SkillGroup[] = [];
  const bare: string[] = [];
  for (const line of lines) {
    const g = parseSkillLine(line);
    if (!g) continue;
    if (g.label) {
      groups.push(g);
    } else {
      // Might carry multiple items already (a "Skills: a, b, c" that lost its label)
      bare.push(...g.items);
    }
  }
  if (bare.length) groups.push({ label: '', items: bare });
  return groups;
}

/** Format one group back to its saved shape. */
export function formatSkillGroup(group: SkillGroup): string {
  const items = group.items.map((s) => s.trim()).filter(Boolean);
  if (!group.label.trim()) {
    // Bare bucket → one comma-separated line, since we don't have a header.
    return items.join(', ');
  }
  return items.length ? `${group.label.trim()}: ${items.join(', ')}` : `${group.label.trim()}:`;
}

/** Serialize the whole editor state back to the `list[str]` the backend expects. */
export function serializeSkillGroups(groups: SkillGroup[]): string[] {
  return groups
    .map(formatSkillGroup)
    .map((s) => s.trim())
    .filter(Boolean);
}
