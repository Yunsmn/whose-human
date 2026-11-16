// Node's built-in https module with its defaults. It sends no User-Agent and no Accept header
// of its own. The POST sets Content-Type and Content-Length, which any form post must send.
//
// Usage: node fetch_https.mjs <base_url> <text>
import https from "node:https";

import { parseArgs, visit } from "./common.mjs";

const { baseUrl, text } = parseArgs(process.argv);

function request(url, options = {}, body = undefined) {
  return new Promise((resolve, reject) => {
    const req = https.request(url, options, (response) => {
      response.resume(); // drain the body
      response.on("end", () => resolve(response.statusCode));
    });
    req.on("error", reject);
    if (body !== undefined) req.write(body);
    req.end();
  });
}

await visit(baseUrl, text, {
  get: (url) => request(url),
  postForm: (url, value) => {
    const body = new URLSearchParams({ text: value }).toString();
    return request(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      body,
    );
  },
});
