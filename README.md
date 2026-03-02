# tatemono-map

## Build & Preview Model (Canonical)

This repository uses **Model B (Committed Public DB Model)** as the single authoritative workflow.

- `data/public/public.sqlite3` is **version-controlled** and treated as the canonical public DB input for publishing.
- GitHub Pages workflow consumes committed `data/public/public.sqlite3` and regenerates `dist/` during CI.
- `scripts/dev_dist.ps1` is for local preview only and **never regenerates or modifies** `public.sqlite3`.
- `scripts/publish_public.ps1` is the **only** script allowed to regenerate `data/public/public.sqlite3`.
- Therefore, Pages output correctness depends on the committed state of `data/public/public.sqlite3`.

```text
Source data -> publish_public.ps1 -> commit public.sqlite3 -> render -> dist -> Pages
```

## Local Preview Rules

Strict local preview rules:

- **DO NOT** open `dist/index.html` via `file://`.
- Always start preview with HTTP server mode:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev_dist.ps1 -Port 8788
```

- Access with:

```text
http://127.0.0.1:8788/tatemono-map/index.html
```

- `scripts/dev_dist.ps1` renders `dist/` from existing public DB and does **not** update `data/public/public.sqlite3`.

## Updating Public DB (Explicit Workflow)

When you intentionally need to update the public DB, follow this exact sequence:

1. Run `scripts/publish_public.ps1`.
2. Confirm `data/public/public.sqlite3` changed intentionally.
3. `git add data/public/public.sqlite3`
4. `git commit`
5. `git push`
6. GitHub Pages workflow regenerates `dist/` automatically from committed `public.sqlite3`.

**Important:** local preview does not update DB. DB updates happen only through `publish_public.ps1`.

## Common Mistakes

- Opening `dist/index.html` with `file://` (breaks JSON fetch/path behavior compared with Pages).
- Assuming `scripts/dev_dist.ps1` updates `public.sqlite3` (it does not).
- Running `publish_public.ps1` accidentally before a simple preview check.
- Getting a dirty `git status` from unintended DB regeneration and mistaking it for preview output.

## Architecture Summary

Model B was chosen to keep one deterministic public input (`data/public/public.sqlite3`) under version control.
Committing the public DB removes ambiguity about what data Pages should render.
This prevents drift between local assumptions and deployed output.
Pages CI always rebuilds `dist/` from the same committed DB snapshot.
Local preview must use HTTP so fetch, base path, and asset behavior match Pages.
For this reason, `file://` preview is intentionally disallowed.
Separating preview (`dev_dist.ps1`) from DB publishing (`publish_public.ps1`) keeps responsibilities explicit and auditable.

## Quick Commands

### Local preview (HTTP, Pages-like)

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev_dist.ps1 -Port 8788
```

### Intentionally publish/update public DB

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\publish_public.ps1 -RepoPath .
```
