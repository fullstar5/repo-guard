import assert from "node:assert/strict";
import { test } from "node:test";

import { parsePositiveInt } from "./ids";

test("accepts positive integer route params", () => {
  assert.equal(parsePositiveInt("1"), 1);
  assert.equal(parsePositiveInt("42"), 42);
});

test("rejects empty, zero, signed, and non-numeric params", () => {
  assert.equal(parsePositiveInt(undefined), null);
  assert.equal(parsePositiveInt(""), null);
  assert.equal(parsePositiveInt("0"), null);
  assert.equal(parsePositiveInt("01"), null);
  assert.equal(parsePositiveInt("-3"), null);
  assert.equal(parsePositiveInt("12abc"), null);
  assert.equal(parsePositiveInt("abc"), null);
});
