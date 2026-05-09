"""dotbio extensions — non-DNA modalities (e.g. methylation).

Each extension lives in its own subpackage and exposes a `compile_*` entry
point that turns its modality-specific input into a `.bio` bundle with the
same facts/, commits/, views/, refs/ shape as the DNA case.
"""
