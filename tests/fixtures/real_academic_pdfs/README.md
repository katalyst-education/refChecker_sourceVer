# Real academic PDF regression fixtures

This directory is for real documents whose provenance, redistribution rights,
and reference ground truth are documented. Do not add user-provided, student,
or otherwise copyrighted PDFs to the repository unless the right to redistribute
them is explicit and recorded. Local-only validation corpora should remain
outside the repository.

For each distributable PDF, add a manifest record containing:

- A stable fixture ID and the PDF's SHA-256 digest.
- Source/provenance (publisher, repository, DOI or URL) and retrieval date.
- The applicable license, license URL, and explicit confirmation that
  redistribution is allowed.
- Document layout and any relevant characteristics (for example, 100+ entries,
  references spanning pages, or an appendix after the bibliography).
- Ground-truth bibliography count and expected titles or persistent identifiers,
  with the independent source used to establish them.

Only claim a completeness or metadata-accuracy result where independent
ground truth is available. A bibliography extracted from the same PDF is not
independent ground truth. Keep ground-truth data minimal and avoid adding
personal information that is not necessary for the regression.

The existing `paper/paper.pdf` and `paper/paper.bib` pair is a repository-local
real-document regression fixture with a six-entry bibliography ground truth.
It does not grant redistribution rights for any other supplied or referenced
document. Synthetic or generated PDFs may be used for narrow unit tests, but
must not be reported as evidence of real-world extraction reliability.

Suggested layout when new rights-cleared fixtures are approved:

```text
tests/fixtures/real_academic_pdfs/
  README.md
  manifest.json
  <stable-fixture-id>.pdf
```
