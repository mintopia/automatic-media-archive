// Reads ama.example.toml, comments included, into the Settings reference page.
//
// The file's layout is the contract:
// - comments before the first table are the page's intro;
// - a comment block right above a table header, or right below it and followed by a
//   blank line, is that table's intro; "Changes apply after a restart." in it marks
//   the table as needing a restart (the mark replaces the sentence on the page);
// - a comment block right above one or more keys is their comment; "SECRET" in it
//   marks them secret. Every key needs one;
// - "#   " (indented) comment lines are preformatted; "#" alone breaks a paragraph;
// - a repeated [[table]] is one table, each key listing every entry's value.

export const RESTART = "Changes apply after a restart.";

export type Block = { text: string } | { code: string };
export interface Key { name: string; values: string[] }
export interface Group { comment: Block[]; keys: Key[]; secret: boolean }
export interface Table { name: string; array: boolean; intro: Block[]; restart: boolean; groups: Group[] }
export interface Reference { intro: Block[]; tables: Table[] }

type Line =
  | { kind: "blank" }
  | { kind: "comment"; text: string }
  | { kind: "header"; name: string; array: boolean }
  | { kind: "key"; name: string; value: string };

function classify(raw: string): Line {
  const line = raw.trim();
  if (line === "") return { kind: "blank" };
  if (line.startsWith("#")) return { kind: "comment", text: line.replace(/^# ?/, "") };
  const header = /^(\[\[?)\s*([^\]]+?)\s*\]\]?$/.exec(line);
  if (header) return { kind: "header", name: header[2], array: header[1] === "[[" };
  const key = /^([A-Za-z0-9_-]+)\s*=\s*(.*)$/.exec(line);
  if (key) return { kind: "key", name: key[1], value: key[2] };
  throw new Error(`ama.example.toml: can't read the line "${line}"`);
}

function blocks(lines: string[]): Block[] {
  const out: Block[] = [];
  for (const line of lines) {
    const last = out.at(-1);
    if (line === "") out.push({ text: "" });
    else if (/^\s{2,}/.test(line)) {
      if (last && "code" in last) last.code += "\n" + line.trim();
      else out.push({ code: line.trim() });
    } else if (last && "text" in last && last.text !== "") last.text += " " + line;
    else out.push({ text: line });
  }
  return out.filter((b) => !("text" in b) || b.text !== "");
}

/** A comment's text as HTML: escaped, with `backticks` as code. */
export function inline(text: string): string {
  const escaped = text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  return escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
}

export function parseExample(source: string): Reference {
  const lines = source.split(/\r?\n/).map(classify);
  const intro: string[] = [];
  const tables: Table[] = [];
  let table: Table | undefined;
  let fresh = false; // this [[table]] entry is the first, so its keys are new
  let comment: string[] = [];
  let pending: string[] | undefined; // a comment block waiting for what follows it
  let group: Group | undefined;

  lines.forEach((line, i) => {
    if (line.kind === "comment") {
      group = undefined;
      comment.push(line.text);
      return;
    }
    if (comment.length) {
      pending = comment;
      comment = [];
    }
    if (line.kind === "blank") {
      group = undefined;
      if (pending) (table ? table.intro.push(...blocks(pending)) : intro.push(...pending, ""));
      pending = undefined;
      return;
    }
    if (line.kind === "header") {
      group = undefined;
      const existing = tables.find((t) => t.name === line.name);
      fresh = !existing;
      table = existing ?? { name: line.name, array: line.array, intro: [], restart: false, groups: [] };
      if (!existing) tables.push(table);
      if (pending) table.intro.push(...blocks(pending));
      pending = undefined;
      return;
    }
    if (!table) throw new Error(`ama.example.toml line ${i + 1}: a key before any table`);
    const known = table.groups.flatMap((g) => g.keys).find((k) => k.name === line.name);
    if (known && !fresh) {
      known.values.push(line.value);
      pending = undefined;
      return;
    }
    if (pending) {
      group = { comment: blocks(pending), keys: [], secret: pending.join(" ").includes("SECRET") };
      table.groups.push(group);
      pending = undefined;
    }
    if (!group) throw new Error(`ama.example.toml: ${table.name}.${line.name} has no comment`);
    group.keys.push({ name: line.name, values: [line.value] });
  });

  for (const t of tables) {
    t.restart = t.intro.some((b) => "text" in b && b.text.includes(RESTART));
    for (const b of t.intro) if ("text" in b) b.text = b.text.replace(RESTART, "").trim();
    t.intro = t.intro.filter((b) => !("text" in b) || b.text !== "");
  }
  return { intro: blocks(intro), tables };
}
