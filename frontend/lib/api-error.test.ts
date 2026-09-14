import assert from "node:assert/strict";
import { test } from "node:test";

import { apiErrorMessage } from "./api-error";

test("uses the fallback for unknown errors", () => {
  assert.equal(apiErrorMessage(new Error("nope"), "Failed."), "Failed.");
});

test("maps 429 to a rate-limit message", () => {
  const error = {
    isAxiosError: true,
    response: { status: 429, data: {} },
  };
  assert.equal(apiErrorMessage(error, "Failed."), "Rate limited. Try again shortly.");
});

test("surfaces FastAPI string detail when present", () => {
  const error = {
    isAxiosError: true,
    response: { status: 400, data: { detail: "User has no Github access token" } },
  };
  assert.equal(apiErrorMessage(error, "Failed."), "User has no Github access token");
});
