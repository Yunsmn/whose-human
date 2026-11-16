// axios with its defaults (Node http adapter). The package to load is the first argument, so
// the same script covers axios 1.8.4 (the version Borysenko 2026 saw from a Node/axios coding agent) and a
// current axios.
//
// Usage: node fetch_axios.mjs <axios-1.8.4|axios-current> <base_url> <text>
import { parseArgs, visit } from "./common.mjs";

const [, , packageName, ...rest] = process.argv;
if (!packageName) {
  console.error("usage: node fetch_axios.mjs <package> <base_url> <text>");
  process.exit(2);
}
const { baseUrl, text } = parseArgs([process.argv[0], process.argv[1], ...rest]);
const axios = (await import(packageName)).default;

// validateStatus: report every status instead of throwing, without changing the request.
const options = { validateStatus: () => true };
await visit(baseUrl, text, {
  get: async (url) => (await axios.get(url, options)).status,
  postForm: async (url, value) => (await axios.post(url, new URLSearchParams({ text: value }), options)).status,
});
