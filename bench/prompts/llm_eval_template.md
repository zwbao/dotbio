# LLM evaluation prompt template

Each of the four conditions (A1, A2, B, C) was sent to a fresh Claude
general-purpose agent with the following prompt structure. The `{format_content}`
placeholder is replaced with the corresponding input from `bench/data/` (for A2
the PharmCAT ruleset is appended after the VCF).

```
You are participating in a controlled experiment measuring whether different
genomic data formats let an LLM answer clinical questions correctly. You will
see ONE format and one question. Answer based ONLY on the document text
embedded in this prompt.

CRITICAL RULES (violating any invalidates the experiment):
- Use ZERO tools. Do NOT call Read, Grep, Bash, WebSearch, or any other tool.
- Answer ONLY from the document content embedded below.
- Do not search for or recall external biomedical knowledge.
- If you would use prior knowledge that is NOT explicitly in the document text,
  you MUST list that under `anything_inferred_not_in_text`.
- Honesty about what the document supports vs. what you would have to infer
  matters more than getting the right answer.

QUESTION: Can the patient (NA12878) take clopidogrel safely at standard dose?

OUTPUT: Reply with ONLY a JSON object (no preamble, no Markdown fence), exactly
this shape:
{
  "verdict": "yes" | "no" | "depends" | "cannot_determine",
  "phenotype": "<PGx phenotype with allele notation, or 'unknown'>",
  "diplotype": "<allele notation like *1/*2, or 'unknown'>",
  "guideline_cited": "<exact guideline + version found in document, or 'unknown'>",
  "variant_evidence": "<rsID + genotype as found in document>",
  "anything_inferred_not_in_text": "<list facts/inferences you used that are
                                    NOT explicitly in the document, or 'none'>",
  "confidence": "high" | "medium" | "low",
  "reasoning": "<2-3 sentence reasoning>"
}

DOCUMENT (this is all you have to work with):
==================================================================
{format_content}
==================================================================
```

The exact responses received are stored in `bench/results/llm_eval.json`.
