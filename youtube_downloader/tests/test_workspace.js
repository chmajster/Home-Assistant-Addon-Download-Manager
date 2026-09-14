"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { parseUrls, validMediaUrl, translate, REQUEST_TIMEOUT_MS } = require("../app/static/js/workspace.js");

test("bulk parser preserves order and deduplicates", () => {
  assert.deepEqual(parseUrls(" https://example.com/a\nhttps://example.com/b;https://example.com/a "), ["https://example.com/a", "https://example.com/b"]);
});
test("empty input produces no candidates", () => {
  for (const input of [null, undefined, "", " \r\n ; , "]) assert.deepEqual(parseUrls(input), []);
});
test("URL validation rejects unsafe schemes, credentials and non-default ports", () => {
  for (const input of ["javascript:alert(1)", "file:///etc/passwd", "https://user:pass@example.com", "http://example.com:8080", "not a URL"]) assert.equal(validMediaUrl(input), false);
});
test("URL validation accepts http and https default ports", () => {
  for (const input of ["https://example.com/a", "http://example.com", "https://example.com:443/a"]) assert.equal(validMediaUrl(input), true);
});
test("translations substitute repeated placeholders without interpreting markup", () => {
  assert.equal(translate({ count: "{n} / {n}" }, "count", { n: 3 }), "3 / 3");
  assert.equal(translate({}, "unknown"), "unknown");
  assert.equal(translate({ label: "{v}" }, "label", { v: "<script>" }), "<script>");
});
test("request timeout is finite and conservative", () => {
  assert.equal(REQUEST_TIMEOUT_MS, 120000);
});
