import { test } from "node:test";
import assert from "node:assert/strict";
import { inline, parseExample } from "./settings.ts";

test("comment text is escaped, with backticks as code", () => {
  assert.equal(inline("Copy `a<b>` & go"), "Copy <code>a&lt;b&gt;</code> &amp; go");
});

const EXAMPLE = `# Where settings live.
#
# Second paragraph.

[web]
# The web UI. Changes apply after a restart.

# Port of the web UI.
port = 8080
# Shared password. SECRET.
password = ""

[scratch]
# Free GB per Disc Type.
cd = 1
dvd = 10

# Libraries: one entry per Library.
[[libraries]]
# Its name.
name = "Movies"

[[libraries]]
name = "TV"
`;

test("the text before the first table is the page intro, in paragraphs", () => {
  assert.deepEqual(parseExample(EXAMPLE).intro, [{ text: "Where settings live." }, { text: "Second paragraph." }]);
});

test("each table has its intro, and the restart sentence marks it", () => {
  const [web, scratch, libraries] = parseExample(EXAMPLE).tables;
  assert.equal(web.name, "web");
  assert.deepEqual(web.intro, [{ text: "The web UI." }]); // the mark says the rest
  assert.equal(web.restart, true);
  assert.equal(scratch.restart, false);
  assert.deepEqual(libraries.intro, [{ text: "Libraries: one entry per Library." }]);
});

test("a key has the comment right above it, its default, and a SECRET mark", () => {
  const [web] = parseExample(EXAMPLE).tables;
  assert.deepEqual(web.groups, [
    { comment: [{ text: "Port of the web UI." }], keys: [{ name: "port", values: ["8080"] }], secret: false },
    { comment: [{ text: "Shared password. SECRET." }], keys: [{ name: "password", values: ['""'] }], secret: true },
  ]);
});

test("keys straight after one another share the comment above them", () => {
  const scratch = parseExample(EXAMPLE).tables[1];
  assert.deepEqual(scratch.groups[0].keys.map((k) => k.name), ["cd", "dvd"]);
});

test("a repeated [[table]] is one table whose keys list every entry's value", () => {
  const { tables } = parseExample(EXAMPLE);
  assert.equal(tables.length, 3);
  assert.equal(tables[2].array, true);
  assert.deepEqual(tables[2].groups[0].keys, [{ name: "name", values: ['"Movies"', '"TV"'] }]);
});

test("indented comment lines are kept as preformatted text", () => {
  const { tables } = parseExample(`[webhook]\n# The body:\n#   {"version": 1}\nurl = ""\n`);
  assert.deepEqual(tables[0].groups[0].comment, [{ text: "The body:" }, { code: '{"version": 1}' }]);
});

test("a key without a comment is an error, so the page can't miss one", () => {
  assert.throws(() => parseExample(`[web]\nport = 8080\n`), /web\.port has no comment/);
});
