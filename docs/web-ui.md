# RefChecker Web UI and API

## Overview

The Web UI provides real-time reference checks for single papers and batches. It includes history, evidence-rich reference cards, corrections, exports, document navigation, graphs, and optional team workflows.

The FastAPI backend is an adapter over the shared `src/refchecker` core. It must not define separate extraction, verification, scoring, or reporting behavior.

## Run locally

```bash
pip install -e ".[webui]"
refchecker-webui
```

Open `http://localhost:8000`.

For frontend development:

```bash
cd web-ui
npm install
npm run dev
```

## Inputs

The interface accepts arXiv identifiers and URLs, PDFs, LaTeX, BibTeX, BBL, plain text, and supported URLs. Batch mode accepts multiple papers and directories through the relevant runner.

## Extraction

If an extraction LLM is configured, it can parse complex bibliographies. Otherwise RefChecker uses deterministic parsers and available fallbacks such as GROBID. Extraction configuration is shared with the CLI and bulk paths.

## Verification

Each extracted reference is checked through the shared source pipeline. The UI displays:

- verified matches and authoritative links;
- warnings for minor or style-dependent differences;
- errors for substantive metadata conflicts;
- unverified results when no reliable source match is available.

## Configuration

Provider credentials can be stored through Settings or supplied as environment variables. Local and hosted modes share the same request schema and core defaults. API keys are optional unless a selected provider requires one.

Settings includes separate model choices for extraction, chat, and summarization.

For a selected history result, unresolved references can use **Suggest alternative reference**. The References header controls the citation style used to render those candidates.

## API behavior

Long-running checks return progress over WebSockets. Completed records store the canonical reference list, summary counts, configuration, and timing information. Export endpoints consume the same stored results; they do not recompute an alternative verdict model.

Important result fields include `paper_title`, `paper_source`, `source_type`, `extraction_method`, `summary`, and `references`. Optional analyses add their own namespaced fields.

## CLI parity

```bash
refchecker-webui check --paper 2406.01234
refchecker-webui check --paper ./paper.pdf --json
refchecker-webui check --paper ./refs.bib --check-retractions --suggest-missing
```

Run `refchecker-webui check --help` for the current options. The same input and configuration should produce matching underlying results through CLI, bulk, and WebUI paths.

## Troubleshooting

- If extraction returns no references, inspect the input format and extraction configuration.
- If references remain unverified, confirm network access, source availability, API keys, and local database paths.
- If a check stalls after a restart, inspect the backend log and reconciliation status.
- If the frontend is stale, rebuild it with `npm run build` and restart the backend.

