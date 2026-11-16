// Node's built-in fetch (undici) with its defaults.
//
// Usage: node fetch_native.mjs <base_url> <text>
import { parseArgs, visit } from "./common.mjs";

const { baseUrl, text } = parseArgs(process.argv);

async function status(response) {
  await response.arrayBuffer(); // read the body so the connection is released normally
  return response.status;
}

await visit(baseUrl, text, {
  get: async (url) => status(await fetch(url)),
  postForm: async (url, value) =>
    status(await fetch(url, { method: "POST", body: new URLSearchParams({ text: value }) })),
});
