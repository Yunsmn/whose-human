# Machine inventory (Track 3)

One row per machine each member will use. Never write real IP addresses here; describe the network type instead.

| Member | Persona id | Machine | OS and version | Node / Python / Go versions | Agents installed (version) | Browser | Network (campus, home, mobile, VPN) |
|---|---|---|---|---|---|---|---|
| A | `persona-a1` | `a-windows` | Windows 11 Pro 10.0.26200, 64-bit | Node 24.20.0 / Python 3.12.10 and 3.14.7 / Go not installed | Codex CLI 0.171.0 (`gpt-5.6-sol` default) | Brave Chromium 158, build 1-100-59 | home; mobile hotspot for setting 4 |
| B | `persona-b1` | `b-windows` | Windows 11 Pro 10.0.26200, 64-bit | Node 22.23.2 / Python 3.12.10 (baselines), 3.11.9 first on PATH / Go 1.27.4 | Claude Code 2.1.319 (default model, `claude-opus-5-5`); Codex CLI 0.172.0 (`gpt-6-luna` only with this login); curl 8.21.0 (Git for Windows, Schannel) and 8.22.0 (System32, Schannel) | Brave Chromium 158, build 1-100-59 | campus; Cloudflare WARP for setting 4 |
| C | | | | | | | |
