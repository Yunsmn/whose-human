// Shared visit sequence for the Node baselines. Every stack does exactly the same four requests,
// so differences in the logs come from the HTTP stack, not from the script.
//
// Usage: node <script>.mjs <base_url> <text>
//   base_url  e.g. https://site1.test:8443/r/b-0001/   (must end with "/")
//   text      the fixed synthetic submission

export function parseArgs(argv) {
  const [baseUrl, text] = argv.slice(2);
  if (!baseUrl || text === undefined) {
    console.error("usage: node <script>.mjs <base_url> <text>");
    process.exit(2);
  }
  return { baseUrl: baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`, text };
}

// steps: { get(url) -> status, postForm(url, text) -> status }
export async function visit(baseUrl, text, steps) {
  const results = [];
  results.push(["GET index.html", await steps.get(new URL("index.html", baseUrl).href)]);
  results.push(["GET input.html", await steps.get(new URL("input.html", baseUrl).href)]);
  const getSubmit = new URL("submit", baseUrl);
  getSubmit.searchParams.set("text", text);
  results.push(["GET submit", await steps.get(getSubmit.href)]);
  results.push(["POST submit", await steps.postForm(new URL("submit", baseUrl).href, text)]);
  let failed = false;
  for (const [step, status] of results) {
    console.log(`${step} ${status}`);
    if (status !== 200) failed = true;
  }
  process.exit(failed ? 1 : 0);
}
