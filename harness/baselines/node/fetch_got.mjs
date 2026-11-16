// got with its defaults (the library Borysenko 2026 saw from Cursor).
//
// Usage: node fetch_got.mjs <base_url> <text>
import got from "got";

import { parseArgs, visit } from "./common.mjs";

const { baseUrl, text } = parseArgs(process.argv);

// throwHttpErrors: report every status instead of throwing, without changing the request.
const options = { throwHttpErrors: false };
await visit(baseUrl, text, {
  get: async (url) => (await got(url, options)).statusCode,
  postForm: async (url, value) => (await got.post(url, { ...options, form: { text: value } })).statusCode,
});
