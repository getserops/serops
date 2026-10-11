# Contributing to SerOps

One guide for the whole repository. The backend, frontend and docs used to live
in three repositories with three near-identical copies of this file; the shared
policy below was duplicated in each and the per-component setup is the only part
that genuinely differed.

## Where to work

This repository is the only place SerOps is developed. `backend/`, `frontend/`
and `docs/` are ordinary directories — edit them in place and commit to `main`
like any other change.

They were once separate GitLab repositories, imported here with `git subtree`
and now archived. **Do not run `git subtree pull`.** The repositories are still
readable, so it would succeed — and it would reinstate the files this repo
deliberately removed: a second copy of the Helm chart under `backend/deploy/`,
and ten GitHub workflows under `backend/.github/` that Actions never runs.
Both duplications have already caused real damage once. The published Helm
chart carried a frontend Service pointing at the wrong port for weeks because
the second copy was the one being edited, and nothing compared the two.

## Before you start

- **Open an issue first for anything non-trivial.** For typo fixes and small bug
  fixes, jump straight to a PR. For anything that changes the API surface, data
  model, or product behaviour, open an issue and let a maintainer weigh in on
  approach before you invest time.
- Read [`SECURITY.md`](./SECURITY.md) if you're reporting or fixing a security
  issue — please do NOT open a public issue for those.

## Contribution terms

SerOps is AGPL-3.0, and a [commercial license](./LICENSE-COMMERCIAL.md) is
offered to organisations that cannot accept copyleft. Offering that second
license requires the project to hold sufficient rights over all the code it
covers, so **code contributions require a signed
[Contributor License Agreement](./CLA.md)**.

It does not take your copyright. You keep it, and you stay free to use your own
work however you like; the agreement grants SerOps the right to ship it in both
the open-source and the commercially licensed editions. Without that right a
contribution cannot appear in a commercial release, and the only remedies later
are to omit it or to track down its author years after the fact.

**Everything that is not code needs no agreement at all** — bug reports, issue
triage, reproduction cases, documentation feedback, design discussion. If you
would rather not sign, those are genuinely useful and we would rather have them
than nothing.

Read [CLA.md](./CLA.md) before opening a pull request, so the agreement is not a
surprise after you have written the code. Signing is by email while the
repository is private; once it is public a CLA assistant bot collects the
signature on each pull request and blocks merge until it is present.

## Branch and PR workflow

0. Sign the [CLA](./CLA.md) if you are contributing code — see above.
1. Fork the repository.
2. Create a topic branch off `main`.
3. Commit in small, reviewable chunks. Keep unrelated cleanup in separate PRs.
4. Push and open a pull request against `main`.
5. CI must be green before review — see the PR template for the checklist.

CI is path-scoped: a frontend-only change does not spend ten minutes booting
Postgres. The live pipeline is [`.gitlab-ci.yml`](./.gitlab-ci.yml) — backend
tests, frontend tests, a strict docs build and a Helm lint.

[`.github/workflows/`](./.github/workflows) holds the same four checks plus
image and chart publishing, ready for an eventual GitHub publish. GitLab does
not read it, so nothing in there runs today. **Change both when you change
either**, or delete one once the hosting question is settled. If workflows ever
do run on GitHub, note they are only read from the repository root — one placed
under `backend/.github/` would look live and run never, which is exactly what
happened to ten of them before the monorepo cutover.

## Reporting bugs and requesting features

Use the issue templates. Include reproduction steps, environment info, and — for
bugs — redacted logs. See [`SECURITY.md`](./SECURITY.md) for security issues.

---

# Backend (`backend/`)

Django 5 REST API plus Celery workers. Requirements: Docker 24+, Docker Compose v2.

```bash
git clone https://github.com/getserops/serops.git
cd serops/backend
cp .env.example .env
# Set DJANGO_SECRET_KEY and the DB credentials.
#
# AI provider keys do NOT go in .env. They are entered in the UI after first
# login (Settings → AI → API Keys) and stored per organisation, encrypted at
# rest. Nothing reads ANTHROPIC_API_KEY or its siblings from the environment.
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

API on http://localhost:8000/api/, Swagger at `/api/docs/`.

**Tests**

```bash
docker exec -e DJANGO_SETTINGS_MODULE=api.test_settings \
  serops_backend_dev python manage.py test --noinput
```

Run the whole suite, not a named subset. CI does the same, deliberately: a
hand-maintained module list goes stale the moment an app is added, and one such
list kept 402 tests hidden behind an empty `tests.py` stub for months.

**Code style**

- **Format**: `ruff format .` (CI runs `ruff format --check`)
- **Lint**: `ruff check .` (CI)
- **Migrations**: run `python manage.py makemigrations --check --dry-run`
  locally before pushing — CI enforces it.
- **Naming**: follow the surrounding file; otherwise standard Django + DRF.
- **Docstrings**: module-level docstrings on new modules. Explain *why* the
  module exists, not what each function does — well-named identifiers cover the
  what.

---

# Frontend (`frontend/`)

React 19 + Vite. Requirements: Node 20+ and a running backend.

```bash
git clone https://github.com/getserops/serops.git
cd serops/frontend
cp .env.example .env             # set VITE_BASE_URL to your backend
npm ci
npm run dev
```

`VITE_BASE_URL` is inlined at **build** time — Vite compiles `import.meta.env`
values into the bundle, so it cannot be changed on a running container. A
published image is built with the relative `/api`, which works for any
deployment whose ingress routes `/api` to the backend.

**Tests**

```bash
npm test             # vitest once (used in CI)
npm run test:watch   # watch mode
npm run lint         # eslint on src/
```

CI runs lint, test and build on every pull request. All three must pass.

**Code style**

- **Lint**: `npm run lint` (auto-fix with `npm run lint:fix`)
- **Components**: read the surrounding file before introducing a new pattern.
  This codebase is intentionally mixed on some things (MUI vs react-bootstrap)
  — favour consistency within a page over global uniformity.
- **State**: prefer React Query for server state; local state stays local.
  Don't reach for Redux.
- **i18n**: any user-facing string goes through `useTranslation()` — English and
  French both need updating.
- **Auth**: use the shared `apiClient` for HTTP calls so the 401 auto-redirect
  works. Do NOT call `fetch` directly against `/api/*`.

---

# Documentation (`docs/`)

MkDocs with the Material theme; Markdown source in `docs/src/`.

```bash
git clone https://github.com/getserops/serops.git
cd serops/docs
pip install mkdocs-material pymdown-extensions
mkdocs serve          # renders at http://localhost:8000
mkdocs build          # production build into ./site
```

**What CI checks**

Every pull request runs `mkdocs build --strict` — that flag turns any broken
internal link into a build failure. Run it locally before pushing.

**Editing rules**

- **Describe what the product actually does**, not what it might do next quarter.
- **When a feature has known limits, say so out loud** (e.g. the Recent
  Resolutions Context page calls out that v1 is recency-based, not
  similarity-based).
- **Prefer concrete examples** — config files, curl invocations, exact dashboard
  paths — over abstract description.
- **Internal strategy notes do not belong here.** They go in the maintainer's
  private notes.
- **Screenshots**: PNG at 2× density, no personal data visible, cropped to the
  relevant panel.

---

## License

By contributing, you agree that your contribution will be licensed under the GNU
AGPL-3.0 (the license this repository ships under). Contributors retain copyright
on their contributions.
