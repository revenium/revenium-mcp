#!/usr/bin/env bash
set -e
# Usage: ./scripts/test.sh [unit|integration|all] [extra pytest args]
MODE=${1:-unit}
shift 1 2>/dev/null || true
case "$MODE" in
  unit)        python -m pytest tests/unit/ -v "$@" ;;
  integration) python -m pytest tests/integration/ -v "$@" ;;
  all)         python -m pytest tests/ -v "$@" ;;
  *)           echo "Usage: $0 [unit|integration|all]"; exit 1 ;;
esac
