#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
pnpm demo:check
pnpm api:check
pnpm check
pnpm test
pnpm build
(cd backend && uv run ruff check . ../scripts/local_infra.py ../scripts/probe_redfox.py ../scripts/database.py ../scripts/contracts.py ../scripts/accounts.py ../scripts/files.py ../scripts/tasks.py ../scripts/frontend_api.py ../scripts/collection.py ../scripts/console_preview.py ../scripts/intelligence_preview.py ../scripts/fill_redfox_keywords.py ../scripts/probe_tikhub_comments.py ../scripts/analyze_comment_sample.py ../scripts/build_sample_insight.py ../scripts/probe_redfox_quality.py ../scripts/fill_redfox_default.py ../scripts/fill_redfox_daily.py ../scripts/probe_tikhub_series.py ../scripts/import_tikhub_series.py ../scripts/validate_research_sample.py ../scripts/research_definitions.py ../scripts/collect_novels.py ../scripts/collect_qidian_mobile.py ../scripts/import_qidian_html.py ../scripts/import_qidian_browser.py && uv run pytest -q)

backend/.venv/bin/python scripts/research_definitions.py --check
