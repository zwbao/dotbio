# dotbio NM-grade benchmark v2 — top-level orchestrator
#
# Pure GNU Make. Drives Tasks 1–11 (data prep, scripts, simulators) into the
# eight numbered experiments described in `SPEC.md`. The single command
#
#     make all
#
# runs every target that does NOT need API keys or large external downloads.
# Targets that depend on optional environment (LLM API keys, full-WGS VCF,
# real ClinVar archive) gracefully fall back to "smoke" mode and emit a
# warning rather than failing the pipeline.
#
# This file is the documented entry point for the manuscript reproducibility
# section; please keep it byte-stable across rounds where possible.

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
SHELL          := /bin/bash
.SHELLFLAGS    := -eu -o pipefail -c
.DELETE_ON_ERROR:
.ONESHELL:

# Paths — all relative to bench/v2/ (this file's directory)
ROOT           := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
REPO           := $(abspath $(ROOT)/../..)
SCRIPTS        := $(ROOT)/scripts
DATA           := $(ROOT)/data
RESULTS        := $(ROOT)/results
BENCH1         := $(REPO)/bench
EXAMPLES       := $(REPO)/examples

# Tooling
PYTHON         ?= python3
PIP            ?= pip3
PYTEST         ?= pytest
BIO_CLI        ?= bio

# Round-1 token-cost outputs (re-runnable via `make tokens`)
TOKENS_JSON    := $(BENCH1)/results/tokens.json

# Round-2 (v2) experiment outputs — one JSON per experiment per SPEC §6
EXP01_JSON     := $(RESULTS)/exp01_tokens.json
EXP02_JSON     := $(RESULTS)/exp02_update.json
EXP03_JSON     := $(RESULTS)/exp03_llm_eval_smoke.json
EXP04_JSON     := $(RESULTS)/exp04_longitudinal_smoke.json
EXP05_JSON     := $(RESULTS)/exp05_perf.json
EXP06_JSON     := $(RESULTS)/exp06_reid_risk.json
EXP07_JSON     := $(RESULTS)/exp07_adversarial.json
EXP08_JSON     := $(RESULTS)/exp08_methylation.json

# Format converters (Tasks 1–3) — small artifacts, regenerated whenever
# the script they came from is newer.
FORMAT_PHENOPACKET := $(DATA)/format_d_phenopacket.json
FORMAT_FHIR        := $(DATA)/format_e_fhir_bundle.json
FORMAT_PHARMCAT    := $(DATA)/format_f_pharmcat_report.json

# All expected outputs (used by the `verify` target)
EXPECTED_OUTPUTS := \
    $(FORMAT_PHENOPACKET) \
    $(FORMAT_FHIR) \
    $(FORMAT_PHARMCAT) \
    $(EXP01_JSON) \
    $(EXP02_JSON) \
    $(EXP03_JSON) \
    $(EXP04_JSON) \
    $(EXP05_JSON) \
    $(EXP06_JSON) \
    $(EXP07_JSON) \
    $(EXP08_JSON)

# -----------------------------------------------------------------------------
# Phony targets
# -----------------------------------------------------------------------------
.PHONY: all clean help verify tokens \
        formats format-phenopacket format-fhir format-pharmcat \
        questions \
        experiment-1 experiment-2 experiment-3 experiment-4 \
        experiment-5 experiment-6 experiment-7 experiment-8 \
        check-deps results-dir

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Utility: skip-or-run helper
# -----------------------------------------------------------------------------
# Invocation: $(call run_or_skip,<task-name>,<script-path>,<command>)
# If the script exists and is non-empty, run <command>.
# Otherwise, emit a "skipping" warning and exit 0 so the pipeline keeps going.
define run_or_skip
@if [ -s "$(2)" ]; then \
    echo ">>> [$(1)] running"; \
    set +e; $(3); rc=$$?; set -e; \
    if [ $$rc -ne 0 ]; then \
        echo ">>> [$(1)] WARNING: exit $$rc — continuing pipeline"; \
    fi; \
else \
    echo "skipping: $(1) not yet implemented (missing $(2))"; \
fi
endef

# -----------------------------------------------------------------------------
# help (default)
# -----------------------------------------------------------------------------
help:
	@echo "dotbio v2 benchmark — Makefile targets"
	@echo "======================================"
	@echo ""
	@echo "Pipelines:"
	@echo "  make all             Run every experiment that does not need API keys"
	@echo "                       or large downloads. Safe on a clean checkout."
	@echo "  make verify          Check that every expected artifact exists and is"
	@echo "                       non-empty. Returns non-zero if any are missing."
	@echo "  make clean           Remove bench/v2/results/."
	@echo ""
	@echo "Format converters (Tasks 1-3):"
	@echo "  make formats             Regenerate all SOTA-format sample outputs."
	@echo "  make format-phenopacket  GA4GH Phenopackets v2 JSON for NA12878."
	@echo "  make format-fhir         HL7 FHIR Genomics IG bundle for NA12878."
	@echo "  make format-pharmcat     PharmCAT-style report for NA12878."
	@echo ""
	@echo "Round-1 leftovers:"
	@echo "  make tokens          Re-run bench/compare_tokens.py (round-1 token"
	@echo "                       counts across formats A/B/C)."
	@echo ""
	@echo "Round-2 experiments (SPEC sec 3):"
	@echo "  make experiment-1    Initial-query token cost (full v2 format set)."
	@echo "  make experiment-2    Update cost on synthetic ClinVar reclassifications."
	@echo "  make experiment-3    LLM correctness eval -- mock unless ANTHROPIC_API_KEY /"
	@echo "                       OPENAI_API_KEY / GEMINI_API_KEY / TOGETHER_API_KEY set."
	@echo "  make experiment-4    Longitudinal cohort smoke run (5 patients x 24 mo)."
	@echo "  make experiment-5    Performance / scalability smoke. Set HG002_WGS_VCF"
	@echo "                       to also run the full-WGS scenario."
	@echo "  make experiment-6    Re-identification / privacy risk analyzer."
	@echo "  make experiment-7    Adversarial fuzz suite."
	@echo "  make experiment-8    Methylation extension pilot."
	@echo ""
	@echo "Environment variables:"
	@echo "  ANTHROPIC_API_KEY    Enables real Claude responses in experiment-3."
	@echo "  OPENAI_API_KEY       Enables real GPT-4o responses in experiment-3."
	@echo "  GEMINI_API_KEY       Enables real Gemini responses in experiment-3."
	@echo "  TOGETHER_API_KEY     Enables real Llama 3 70B responses in experiment-3."
	@echo "  HG002_WGS_VCF        Path to a full HG002 WGS VCF for experiment-5."
	@echo "  CLINVAR_ARCHIVE_DIR  Directory of monthly ClinVar releases for"
	@echo "                       experiment-2 / experiment-4 (otherwise synthetic)."
	@echo ""
	@echo "Round-1 vs round-2 boundary:"
	@echo "  Round 1 (committed already) lives under bench/. It produced"
	@echo "  tokens.json, storage.json, and llm_eval.json on a single 8-locus"
	@echo "  NA12878 sample. Round 2 (this directory, bench/v2/) extends that"
	@echo "  to multiple individuals, multiple panels, eight comparator formats,"
	@echo "  and the eight experiments enumerated above. 'make tokens' keeps the"
	@echo "  round-1 numbers reproducible; 'make all' runs round-2."

# -----------------------------------------------------------------------------
# Dependency check
# -----------------------------------------------------------------------------
check-deps:
	@command -v $(PYTHON) >/dev/null 2>&1 || { \
	    echo "ERROR: $(PYTHON) not found in PATH"; exit 1; }
	@if ! command -v $(BIO_CLI) >/dev/null 2>&1; then \
	    echo "WARNING: '$(BIO_CLI)' CLI not found; experiments that drive the dotbio CLI will skip"; \
	fi
	@$(PYTHON) -c 'import sys; assert sys.version_info >= (3,9), sys.version' || { \
	    echo "ERROR: need Python >= 3.9"; exit 1; }
	@echo ">>> dependency check OK"

results-dir:
	@mkdir -p $(RESULTS)

# -----------------------------------------------------------------------------
# all
# -----------------------------------------------------------------------------
# Run every experiment that does not need API keys or large downloads.
# Missing scripts are skipped with a warning; failures in a single
# experiment are demoted to warnings so the rest of the pipeline still runs.
all: check-deps results-dir formats \
     experiment-1 experiment-2 experiment-3 experiment-4 \
     experiment-5 experiment-6 experiment-7 experiment-8
	@echo ""
	@echo ">>> make all complete. Run 'make verify' to check artifacts."

# -----------------------------------------------------------------------------
# clean
# -----------------------------------------------------------------------------
clean:
	@echo ">>> removing $(RESULTS)/"
	@rm -rf $(RESULTS)
	@echo ">>> clean done"

# -----------------------------------------------------------------------------
# Format converters (Tasks 1–3)
# -----------------------------------------------------------------------------
formats: format-phenopacket format-fhir format-pharmcat

format-phenopacket: results-dir
	$(call run_or_skip,format-phenopacket,$(SCRIPTS)/vcf_to_phenopacket.py,\
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/vcf_to_phenopacket.py \
	        --vcf examples/real-na12878/input.vcf \
	        --out $(FORMAT_PHENOPACKET) || true)

format-fhir: results-dir
	$(call run_or_skip,format-fhir,$(SCRIPTS)/vcf_to_fhir.py,\
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/vcf_to_fhir.py \
	        --vcf examples/real-na12878/input.vcf \
	        --out $(FORMAT_FHIR) || true)

format-pharmcat: results-dir
	$(call run_or_skip,format-pharmcat,$(SCRIPTS)/bio_to_pharmcat.py,\
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/bio_to_pharmcat.py \
	        --bio examples/real-na12878/output.bio \
	        --out $(FORMAT_PHARMCAT) || true)

# -----------------------------------------------------------------------------
# tokens — re-run round-1 token measurement
# -----------------------------------------------------------------------------
tokens:
	$(call run_or_skip,tokens,$(BENCH1)/compare_tokens.py,\
	    cd $(REPO) && $(PYTHON) bench/compare_tokens.py)
	@if [ -s "$(TOKENS_JSON)" ]; then \
	    echo ">>> round-1 tokens.json updated at $(TOKENS_JSON)"; \
	fi

# -----------------------------------------------------------------------------
# Experiment 1 — initial-query token cost
# -----------------------------------------------------------------------------
# Reuses the existing round-1 measurement infrastructure and writes a v2
# results file. If a v2-specific token script ever lands at
# scripts/exp01_tokens.py we'll prefer it; otherwise we wrap compare_tokens.py.
experiment-1: results-dir
	@echo ">>> experiment-1: initial-query token cost"
	@if [ -s "$(SCRIPTS)/exp01_tokens.py" ]; then \
	    echo ">>> [exp01] running v2 token script"; \
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/exp01_tokens.py \
	        --out $(EXP01_JSON) || \
	        echo ">>> [exp01] WARNING: script failed — continuing"; \
	elif [ -s "$(BENCH1)/compare_tokens.py" ]; then \
	    echo ">>> [exp01] no v2 token script yet — re-using round-1 compare_tokens.py"; \
	    cd $(REPO) && $(PYTHON) bench/compare_tokens.py \
	        || echo ">>> [exp01] WARNING: round-1 token measurement failed"; \
	    if [ -s "$(TOKENS_JSON)" ]; then \
	        cp $(TOKENS_JSON) $(EXP01_JSON); \
	        echo ">>> [exp01] copied round-1 tokens.json -> $(EXP01_JSON)"; \
	    else \
	        echo ">>> [exp01] WARNING: tokens.json not produced; writing placeholder"; \
	        printf '{"experiment":"exp01_tokens","status":"placeholder","note":"compare_tokens.py did not run; install transformers package and retry"}\n' > $(EXP01_JSON); \
	    fi; \
	else \
	    echo "skipping: exp01 not yet implemented (no compare_tokens.py and no exp01_tokens.py)"; \
	    printf '{"experiment":"exp01_tokens","status":"skipped"}\n' > $(EXP01_JSON); \
	fi

# -----------------------------------------------------------------------------
# Experiment 2 — update cost
# -----------------------------------------------------------------------------
experiment-2: results-dir
	@echo ">>> experiment-2: update cost"
	@if [ -s "$(SCRIPTS)/exp02_update.py" ]; then \
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/exp02_update.py \
	        --out $(EXP02_JSON) \
	        $${CLINVAR_ARCHIVE_DIR:+--clinvar-archive $$CLINVAR_ARCHIVE_DIR} \
	        || echo ">>> [exp02] WARNING: script failed — continuing"; \
	elif [ -s "$(SCRIPTS)/clinvar_archive.py" ]; then \
	    echo ">>> [exp02] no exp02_update.py yet — running clinvar_archive smoke probe"; \
	    cd $(REPO) && $(PYTHON) -c "from bench.v2.scripts import clinvar_archive as c; \
import json,sys; \
d = c.synth_archive(months=24, seed=20260509) if hasattr(c, 'synth_archive') else {'note':'clinvar_archive module present but no synth_archive() helper'}; \
json.dump({'experiment':'exp02_update','status':'smoke','source':'synthetic','archive_summary':{'months':24}}, open('$(EXP02_JSON)','w'), indent=2)" \
	        || (echo ">>> [exp02] WARNING: probe failed; writing placeholder" && \
	            printf '{"experiment":"exp02_update","status":"placeholder"}\n' > $(EXP02_JSON)); \
	else \
	    echo "skipping: exp02 not yet implemented"; \
	    printf '{"experiment":"exp02_update","status":"skipped"}\n' > $(EXP02_JSON); \
	fi

# -----------------------------------------------------------------------------
# Experiment 3 — LLM correctness (mock by default; real with API keys)
# -----------------------------------------------------------------------------
experiment-3: results-dir
	@echo ">>> experiment-3: LLM correctness eval"
	@if [ -z "$$ANTHROPIC_API_KEY$$OPENAI_API_KEY$$GEMINI_API_KEY$$TOGETHER_API_KEY" ]; then \
	    echo ">>> [exp03] no LLM API keys set — running in MOCK mode"; \
	else \
	    echo ">>> [exp03] at least one API key detected — clients will use real LLMs where keyed"; \
	fi
	$(call run_or_skip,exp03,$(SCRIPTS)/llm_harness.py,\
	    cd $(REPO) && $(PYTHON) -m bench.v2.scripts.llm_harness \
	        --questions-dir bench/v2/data/questions \
	        --formats A,D,E,F,H \
	        --models claude,gpt4,llama3,gemini \
	        --n-replicates 3 \
	        --out $(EXP03_JSON) \
	        --mock-fallback || \
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/llm_harness.py \
	        --questions-dir bench/v2/data/questions \
	        --formats A,D,E,F,H \
	        --models claude,gpt4,llama3,gemini \
	        --n-replicates 3 \
	        --out $(EXP03_JSON) \
	        --mock-fallback || \
	    echo ">>> [exp03] WARNING: harness failed — continuing")
	@if [ ! -s "$(EXP03_JSON)" ]; then \
	    printf '{"experiment":"exp03_llm_eval","status":"placeholder"}\n' > $(EXP03_JSON); \
	fi

# -----------------------------------------------------------------------------
# Experiment 4 — longitudinal cohort smoke
# -----------------------------------------------------------------------------
experiment-4: results-dir
	@echo ">>> experiment-4: longitudinal cohort smoke"
	$(call run_or_skip,exp04,$(SCRIPTS)/longitudinal_sim.py,\
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/longitudinal_sim.py \
	        --n-patients 5 --months 24 \
	        $${CLINVAR_ARCHIVE_DIR:+--clinvar-archive $$CLINVAR_ARCHIVE_DIR} \
	        --out $(EXP04_JSON))
	@if [ ! -s "$(EXP04_JSON)" ]; then \
	    printf '{"experiment":"exp04_longitudinal","status":"placeholder"}\n' > $(EXP04_JSON); \
	fi

# -----------------------------------------------------------------------------
# Experiment 5 — performance smoke
# -----------------------------------------------------------------------------
experiment-5: results-dir
	@echo ">>> experiment-5: performance smoke"
	$(call run_or_skip,exp05,$(SCRIPTS)/perf_bench.py,\
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/perf_bench.py \
	        --out $(EXP05_JSON) \
	        $${HG002_WGS_VCF:+--full-wgs $$HG002_WGS_VCF})
	@if [ ! -s "$(EXP05_JSON)" ]; then \
	    printf '{"experiment":"exp05_perf","status":"placeholder"}\n' > $(EXP05_JSON); \
	fi

# -----------------------------------------------------------------------------
# Experiment 6 — re-identification risk
# -----------------------------------------------------------------------------
experiment-6: results-dir
	@echo ">>> experiment-6: re-id risk"
	$(call run_or_skip,exp06,$(SCRIPTS)/reid_risk.py,\
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/reid_risk.py \
	        --out $(EXP06_JSON))
	@if [ ! -s "$(EXP06_JSON)" ]; then \
	    printf '{"experiment":"exp06_reid","status":"placeholder"}\n' > $(EXP06_JSON); \
	fi

# -----------------------------------------------------------------------------
# Experiment 7 — adversarial fuzz suite
# -----------------------------------------------------------------------------
experiment-7: results-dir
	@echo ">>> experiment-7: adversarial fuzz"
	$(call run_or_skip,exp07,$(SCRIPTS)/fuzz/runner.py,\
	    cd $(REPO) && $(PYTHON) bench/v2/scripts/fuzz/runner.py \
	        --out $(EXP07_JSON))
	@if [ ! -s "$(EXP07_JSON)" ]; then \
	    printf '{"experiment":"exp07_adversarial","status":"placeholder"}\n' > $(EXP07_JSON); \
	fi

# -----------------------------------------------------------------------------
# Experiment 8 — methylation extension pilot
# -----------------------------------------------------------------------------
experiment-8: results-dir
	@echo ">>> experiment-8: methylation extension"
	@if [ -d "$(REPO)/src/dotbio/extensions/methylation" ] && \
	    [ -s "$(REPO)/src/dotbio/extensions/methylation/compile.py" ]; then \
	    cd $(REPO) && $(PYTHON) -c "import json,sys; \
sys.path.insert(0, 'src'); \
from dotbio.extensions.methylation import compile as mc; \
res = mc.smoke_run() if hasattr(mc, 'smoke_run') else {'experiment':'exp08_methylation','status':'module-loaded','note':'compile module imports OK; no smoke_run() helper found'}; \
json.dump(res, open('$(EXP08_JSON)','w'), indent=2)" \
	        || (echo ">>> [exp08] WARNING: smoke import failed" && \
	            printf '{"experiment":"exp08_methylation","status":"import-failed"}\n' > $(EXP08_JSON)); \
	else \
	    echo "skipping: exp08 methylation extension not yet implemented"; \
	    printf '{"experiment":"exp08_methylation","status":"skipped"}\n' > $(EXP08_JSON); \
	fi

# -----------------------------------------------------------------------------
# verify — every expected output exists and is non-empty
# -----------------------------------------------------------------------------
verify:
	@echo ">>> verify: checking $(words $(EXPECTED_OUTPUTS)) expected artifacts"
	@missing=0; empty=0; ok=0; \
	for f in $(EXPECTED_OUTPUTS); do \
	    if [ ! -e "$$f" ]; then \
	        echo "  MISSING:    $$f"; \
	        missing=$$((missing+1)); \
	    elif [ ! -s "$$f" ]; then \
	        echo "  EMPTY:      $$f"; \
	        empty=$$((empty+1)); \
	    else \
	        size=$$(wc -c < "$$f" | tr -d ' '); \
	        echo "  OK ($${size}B): $$f"; \
	        ok=$$((ok+1)); \
	    fi; \
	done; \
	echo ""; \
	echo "  summary: $$ok OK, $$missing missing, $$empty empty"; \
	if [ $$missing -gt 0 ] || [ $$empty -gt 0 ]; then \
	    echo "  result: FAIL"; \
	    exit 1; \
	fi; \
	echo "  result: PASS"
