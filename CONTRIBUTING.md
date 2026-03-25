# Contributing to VoxWatch

Thanks for your interest in contributing. This guide covers everything you need
to get a local dev environment running and submit a pull request.

---

## Prerequisites

- Python 3.11+
- Node 18+
- Docker + Docker Compose
- A running Frigate NVR instance (or the mock server for frontend-only work)

---

## Development Setup

```bash
# 1. Clone the repo
git clone https://github.com/yourusername/voxwatch.git
cd voxwatch

# 2. Python — install core package and dev deps
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Frontend — install dependencies
cd dashboard/frontend
npm install

# 4. Backend API — install deps (shares the venv above)
cd ../backend
pip install -r requirements.txt
```

### Running Locally

```bash
# Terminal 1: FastAPI backend (from dashboard/backend/)
uvicorn main:app --reload --port 8000

# Terminal 2: React dev server (from dashboard/frontend/)
npm run dev

# Dashboard is at http://localhost:5173
# API is at http://localhost:8000
```

---

## Project Structure

```
voxwatch/           Core Python package — detection, AI, TTS, audio push
  config.py         Pydantic config model and YAML loader
  deterrent.py      Orchestrates the three-stage deterrent pipeline
  audio_push.py     go2rtc backchannel audio delivery

dashboard/
  backend/          FastAPI REST + WebSocket API
    routers/        One router per resource (config, status, cameras)
    models/         Pydantic request/response models

  frontend/         React 18 + TypeScript + Tailwind dashboard
    src/
      components/   UI components (common/, config/, status/)
      constants/    Shared constants (AI costs, etc.)
      hooks/        React Query hooks for API + WebSocket data
      pages/        Top-level page components
      types/        Shared TypeScript types
```

---

## Running Tests

```bash
# Python unit + integration tests
pytest

# Frontend component and hook tests
cd dashboard/frontend
npm test

# Frontend tests with coverage report
npm test -- --coverage
```

---

## Code Style

**Python**
- Format: `black .`
- Lint: `ruff check .`
- Both run automatically via pre-commit if you install it: `pre-commit install`

**TypeScript / React**
- Format: `prettier --write .` (or `npm run format`)
- Lint: `eslint src/` (or `npm run lint`)
- Strict TypeScript is enabled — avoid `any`, use proper types

---

## Pull Request Guidelines

- **Keep PRs focused.** One feature or fix per PR makes review faster.
- **Describe the why.** The PR description should explain the problem being
  solved, not just list what changed.
- **Include tests.** New behaviour should have a pytest test or React Testing
  Library test. Bug fixes should include a regression test.
- **Match the style.** Run the formatters before pushing.
- **Target `main`.** All PRs merge into the main branch.

For large changes, open an issue first to discuss the approach before writing
code. This avoids wasted effort if the direction needs adjustment.
