# RefChecker features

RefChecker extracts bibliographic references and verifies them against scholarly sources. It reports evidence-backed matches, metadata discrepancies, and explicit abstentions.

## Result model

| Status | Meaning |
|---|---|
| Verified | An authoritative record supports the citation |
| Warning | A minor or style-dependent discrepancy needs review |
| Error | Substantive cited metadata conflicts with the resolved source |
| Unverified | No source resolved the citation with enough confidence |

An unverified reference is not classified beyond the available evidence.

## Shared capabilities

| Capability | Web | Desktop | CLI | API |
|---|:---:|:---:|:---:|:---:|
| Reference extraction | Yes | Yes | Yes | Yes |
| Multi-source verification | Yes | Yes | Yes | Yes |
| LLM-assisted extraction | Yes | Yes | Yes | Yes |
| Batch processing | Yes | Yes | Yes | Yes |
| Inline-citation numbering checks | Yes | Yes | Yes | Yes |
| Retraction screening | Yes | Yes | Yes | Yes |
| Structured reports | Yes | Yes | Yes | Yes |
| Citation corrections and exports | Yes | Yes | Yes | Yes |
| Interactive document views | Yes | Yes | No | No |
| Citation and library graphs | Yes | Yes | No | API data |

All execution paths call the same modules in `src/refchecker`. Configuration, prompts, thresholds, error categories, and report fields must remain aligned.

## Inputs

- arXiv identifier or URL
- PDF
- LaTeX
- BibTeX and BBL
- plain text
- supported scholarly URLs
- lists and directories for batch runs

## Verification sources

Depending on the reference type and local configuration, RefChecker can query Semantic Scholar, OpenAlex, Crossref, DBLP, ACL Anthology, arXiv, PubMed, Google Books, and local database snapshots.

## Evidence and enrichment

Resolved references can include normalized identifiers, authoritative URLs, corrected metadata, abstracts, citation counts, open-access links, funding information, and source-by-source diagnostics. Optional enrichments never replace the core verification verdict without recorded evidence.

## Reports

Structured output is available in JSON and JSONL. User-facing exports include text, CSV, Markdown, HTML, PDF, DOCX, BibTeX, and RIS where supported. Reports preserve the cited metadata, resolved metadata, issue categories, evidence links, and run configuration needed for auditability.

## Reproducibility

For experiments, pin the revision and dependency set; preserve input hashes and structured outputs; record provider/model settings, enabled sources, cache state, and run date; and report unverified references as abstentions.

