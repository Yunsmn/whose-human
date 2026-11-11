# Contributing

## Branches

- `main` is protected. Nobody pushes to it directly; every change arrives through a pull request.
- Each member works on their own branch, named after themselves, for example `younes`. Splitting further is optional: one branch per piece (`younes/1a-agent-runs`) keeps pull requests small and easy to review.
- Bring `main` into your branch often (`git pull origin main`), at least before opening a PR, so conflicts stay small.

```
git switch -c <your-name>          # once
# ... work, commit ...
git pull origin main               # sync before opening a PR
git push -u origin <your-name>
gh pr create --base main           # or open the PR on GitHub
```

## Pull requests

A PR can merge into `main` only when:

1. **CI is green** (see below).
2. **One teammate has approved it.** The author can't approve their own PR.
3. **It is up to date with `main`.**

Keep PRs focused on one piece (see `TEAM.md`). If a PR changes `infra/` or `infra/schema.md`, say so in the title; those changes need the whole team to agree.

## CI

`.github/workflows/ci.yml` runs on every PR and on every push to `main`:

| Step | What it checks |
|---|---|
| Private data guard | No raw logs (`*.jsonl`, `*.pcap`, `*.har`, `*.log`, `data/`) and no public IP addresses in committed files |
| `ruff check .` | Lint |
| `ruff format --check .` | Formatting |
| `pytest` | Tests in `harness/tests`, `model/tests`, `linking/tests`, `infra/` |

Run the same checks locally before pushing:

```
pip install -r requirements-dev.txt
python .github/scripts/check_no_private_data.py
ruff check . && ruff format --check .
pytest
```

`ruff format .` fixes formatting for you. In examples and tests, use documentation IP addresses (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`); the guard lets them through.

## Commits

Use the format `<type>: <description>`, where type is one of `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.
