import { test } from "node:test";
import assert from "node:assert/strict";
import { neighbours, sectionOf } from "./docs.ts";

test("next page crosses into the following section", () => {
  assert.deepEqual(
    neighbours("setup").next,
    { slug: "how-a-disc-flows", title: "How a Disc flows" },
  );
});

test("the first page has no previous page and the last has no next", () => {
  assert.equal(neighbours("install").prev, undefined);
  assert.equal(neighbours("contributing").next, undefined);
});

test("the open tab is the section holding the page", () => {
  assert.equal(sectionOf("libraries").label, "How it works");
});
