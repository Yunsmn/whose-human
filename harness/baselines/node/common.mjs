// Shared visit sequence for the Node baselines. Every stack does exactly the same four requests,
// so differences in the logs come from the HTTP stack, not from the script.
//
// Usage: node <script>.mjs <base_url> <text>
//   base_url  e.g. https://site1.test:8443/r/b-0001/   (must end with "/")
//   text      the fixed synthetic submission
//
// WH_THINK_TIME (set by the runner's --think-time) adds a pause before every request after the
// first: "3" waits 3 seconds, "2-6" a random time between 2 and 6 seconds. Unset: no pause.

export function thinkRange(value = process.env.WH_THINK_TIME) {
  if (!value || !value.trim()) return [0, 0];
  const match = /^(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?$/.exec(value.trim());
  const lo = match ? Number(match[1]) : NaN;
  const hi = match && match[2] !== undefined ? Number(match[2]) : lo;
  if (!(lo >= 0 && hi >= lo)) {
    console.error(`invalid WH_THINK_TIME=${JSON.stringify(value)}: use seconds (3) or a range (2-6)`);
    process.exit(2);
  }
  return [lo, hi];
}

async function think() {
  const [lo, hi] = thinkRange();
  if (hi > 0) await new Promise((resolve) => setTimeout(resolve, (lo + Math.random() * (hi - lo)) * 1000));
}

export function parseArgs(argv) {
  const [baseUrl, text] = argv.slice(2);
  if (!baseUrl || text === undefined) {
    console.error("usage: node <script>.mjs <base_url> <text>");
    process.exit(2);
  }
  thinkRange(); // fail before the first request, not halfway through
  return { baseUrl: baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`, text };
}

// steps: { get(url) -> status, postForm(url, text) -> status }
export async function visit(baseUrl, text, steps) {
  const results = [];
  results.push(["GET index.html", await steps.get(new URL("index.html", baseUrl).href)]);
  await think();
  results.push(["GET input.html", await steps.get(new URL("input.html", baseUrl).href)]);
  const getSubmit = new URL("submit", baseUrl);
  getSubmit.searchParams.set("text", text);
  await think();
  results.push(["GET submit", await steps.get(getSubmit.href)]);
  await think();
  results.push(["POST submit", await steps.postForm(new URL("submit", baseUrl).href, text)]);
  let failed = false;
  for (const [step, status] of results) {
    console.log(`${step} ${status}`);
    if (status !== 200) failed = true;
  }
  process.exit(failed ? 1 : 0);
}
