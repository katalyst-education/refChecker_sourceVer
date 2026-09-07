# Academic RefChecker

Academic RefChecker is an open-source tool for extracting bibliographic references from scholarly documents and verifying their metadata against independent academic sources.

It supports three equivalent execution paths:

- Web and desktop interface for interactive review.
- Command line for a single paper or scripted batches.
- Shared Python core for integrations and reproducible experiments.

All paths use the same extraction, verification, scoring, and reporting logic.

## What it checks

RefChecker extracts references and compares the cited metadata with records from sources such as Semantic Scholar, OpenAlex, Crossref, DBLP, ACL Anthology, arXiv, PubMed, and Google Books where applicable.

Results use four primary outcomes:

- **Verified** — an authoritative record supports the citation.
- **Warning** — the work was found, but a minor or style-dependent discrepancy needs review.
- **Error** — the work was found, but substantive cited metadata conflicts with the source.
- **Unverified** — no authoritative source resolved the citation with enough confidence.

An unverified result is an abstention, not a claim that a citation is fabricated.

## Core capabilities

- PDF, LaTeX, BibTeX, BBL, text, URL, and arXiv input.
- LLM-assisted or structural reference extraction.
- Multi-source metadata verification and identifier normalization.
- Reference-level evidence, corrections, and authoritative links.
- Inline-citation numbering checks.
- Retraction screening.
- Citation-context and related-work exploration.
- Single-paper and batch processing.
- JSON, JSONL, CSV, text, Markdown, HTML, PDF, DOCX, BibTeX, and RIS output where supported.
- Local history, team workflows, and interactive document views in the Web UI.

## Installation

Python 3.10 or newer is recommended.

```bash
git clone <repository-url>
cd refchecker
python -m venv .venv
```

Activate the environment and install the package:

```bash
pip install -e ".[webui]"
```

For development:

```bash
pip install -r requirements-dev.txt
cd web-ui
npm install
```

## Quick start

Start the Web UI:

```bash
refchecker-webui
```

Then open `http://localhost:8000`.

Check one paper from the command line:

```bash
refchecker-webui check --paper 2406.01234
refchecker-webui check --paper ./paper.pdf --json
refchecker-webui check --paper ./references.bib
```

The legacy entry point remains available:

```bash
python run_refchecker.py --paper ./paper.pdf
```

Run `refchecker-webui check --help` for the authoritative option list.

## Configuration

LLM configuration is optional. Without an extraction model, RefChecker uses deterministic extraction and available parsing fallbacks. Supported provider integrations are configured through environment variables or the Web UI.

Useful optional keys include:

```text
SEMANTIC_SCHOLAR_API_KEY=
GOOGLE_BOOKS_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
AZURE_OPENAI_API_KEY=
```

Never commit real credentials. Use a local `.env` file or the settings interface.

## Reproducible use

For an evaluation or technical paper:

1. Pin the repository revision and dependency versions.
2. Record the input corpus and inclusion criteria.
3. Record the extraction mode, provider/model, source configuration, and thresholds.
4. Preserve the structured JSON or JSONL outputs.
5. Report unresolved citations as abstentions.
6. Separate extraction accuracy from verification accuracy.
7. Measure path parity by running identical inputs through CLI and API/WebUI adapters.
8. Document network-source availability, rate limits, cache state, and run date.

The shared result model and report builders are intended to make those experiments auditable.

## Repository layout

```text
src/refchecker/     shared extraction and verification core
backend/            FastAPI transport, persistence, exports, and WebUI adapter
web-ui/             React interface
tests/              unit and integration tests
paper/              technical-paper sources
scripts/            database and operational utilities
tauri-app/          desktop packaging
```

## Development checks

```bash
pytest
cd web-ui
npm test -- --run
npm run build
```

When changing behavior, verify that bulk, CLI, and WebUI paths produce the same underlying reference results for the same configuration.

## Documentation

- [Feature overview](docs/FEATURES.md)
- [Web UI and API guide](docs/web-ui.md)
- [Design system](docs/design.md)
- [Technical paper](paper/paper.md)
- [Contributing](CONTRIBUTING.md)

## License

See [LICENSE](LICENSE).

