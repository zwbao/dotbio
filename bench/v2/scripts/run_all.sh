#!/usr/bin/env bash
# run_all.sh — convenience wrapper that runs the full v2 benchmark via Make.
#
# This is the documented one-command entry point for the manuscript
# reproducibility section. It simply runs `make all` from bench/v2/ with
# sensible defaults, then `make verify` to confirm the artifacts.
#
# Usage:
#   bash bench/v2/scripts/run_all.sh           # default: full pipeline
#   bash bench/v2/scripts/run_all.sh -j 4      # parallel make
#   bash bench/v2/scripts/run_all.sh experiment-3   # one target
#
# Environment variables (all optional — pipeline runs without them):
#   ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, TOGETHER_API_KEY
#       Enables real LLM calls in experiment-3 (otherwise mock mode).
#   HG002_WGS_VCF
#       Path to a full HG002 WGS VCF for experiment-5 large-scale tier.
#   CLINVAR_ARCHIVE_DIR
#       Directory of monthly ClinVar releases for experiment-2/-4.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${V2_DIR}"

# Defaults: parallel where safe, no implicit rules, fail-soft per target
# (Makefile already demotes per-experiment failures to warnings).
MAKE_ARGS=("--no-builtin-rules" "--no-print-directory")

# If the user passed any args, forward them; otherwise default to `all`.
if [[ $# -eq 0 ]]; then
    TARGETS=("all")
else
    TARGETS=("$@")
fi

echo ">>> dotbio v2 benchmark — running: make ${TARGETS[*]}"
echo ">>> working dir: ${V2_DIR}"
echo ""

make "${MAKE_ARGS[@]}" "${TARGETS[@]}"

echo ""
echo ">>> verifying outputs..."
# Run verify but never fail this script on it — verify is informational at
# the wrapper level; a real CI run should call `make verify` directly.
if make "${MAKE_ARGS[@]}" verify; then
    echo ">>> all expected artifacts present"
else
    echo ">>> some artifacts missing or empty (see above) — exit code suppressed in wrapper"
fi
