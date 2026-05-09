# Cover letter

Dear Editor,

We submit a Methods manuscript describing **dotbio**, a content-addressed, append-only bundle format that separates immutable biological facts from versioned interpretations so that a `.bio` bundle remains legible to a language model, auditable by a clinician, and answerable across years of guideline drift — properties that VCF, .genome, FHIR Genomics, and Phenopackets each, by design, sacrifice.

The format is one contribution; the accompanying round-1 benchmark is a second. We assembled NA12878 plus six additional GIAB individuals (HG002–HG007) into a multi-format comparison spanning VCF, PharmCAT JSON, Phenopackets v2, FHIR R4 Genomics bundles, a `.genome` reconstruction, and `.bio`. We measured token cost on a real Claude tokenizer, correctness on a CPIC-grounded clopidogrel question, longitudinal performance on 24 months of synthetic ClinVar transitions, re-identification entropy (Erlich–Narayanan), adversarial robustness across 29 fuzz cases, performance from cold-compile through 100-run query latency, and a methylation-extension pilot on the Horvath clock to demonstrate generalizability beyond DNA.

Three findings stand out and are quantitative claims in the manuscript. First, on the NA12878 clopidogrel question, only `.bio` cited the CPIC@2022 guideline by name and version while reaching the correct verdict, at 834 tokens versus 13,887 for FHIR. Second, on synthetic 24-month longitudinal data, monthly `bio update` reached a 0.000 false-negative rate on actionable reclassifications versus 0.574 for the standard-of-care quarterly re-annotation arm, at ~2.4× cumulative token cost. Third, the format passed every fuzz case across malformed VCF, conflicting rulesets, schema migration, and hash collision attempts.

We are explicit about round-1 limits. The LLM evaluation is single-shot (N=1); round-2 will be N=30 × 4 LLMs × 50 questions, pre-registered on OSF. The longitudinal cohort uses synthetic ClinVar transitions; round-2 will use the real 24-month NCBI archive. The methylation pilot uses deterministic-synthetic Horvath coefficients; round-2 will use the published 353-coefficient table. There is no clinical user study yet, and `.bio` is not clinically validated. We submit this as a methods description of a format ready for community evaluation rather than a clinical claim, which we believe is appropriate scope for the main track.

The format specification, all benchmark code and result JSONs, and a Make-driven reproducibility entry point live at github.com/zwbao/dotbio under Apache 2.0; pre-registration of the round-2 evaluation plan is in preparation on OSF.

Thank you for considering the manuscript.

Sincerely,

Z. Bao
on behalf of the dotbio authors
