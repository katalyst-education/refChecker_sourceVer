# RefChecker design system

The interface is evidence-first: status, source, and suggested correction should be understandable without interpreting model internals.

## Status language

| Status | Meaning |
|---|---|
| Verified | Authoritative metadata supports the citation |
| Warning | Review a minor or style-dependent difference |
| Error | Resolved metadata conflicts with the citation |
| Unverified | Available sources did not establish a reliable match |

Errors take precedence over warnings. When neither is present, the verified or unverified outcome determines the status. All views and exports use the same shared status logic.

## Visual principles

- Use the project color tokens rather than new hard-coded colors.
- Pair color with a label or icon; color is never the only signal.
- Keep evidence and authoritative links close to the verdict.
- Display cited and resolved metadata separately.
- Treat missing evidence as an abstention.
- Keep destructive actions visually distinct and reversible where possible.
- Preserve control positions while details expand below them.

## Components

- Summary cards show canonical counts from the shared result model.
- Reference rows show status, cited metadata, issues, corrections, and sources.
- Document views connect inline citations with their bibliography entries.
- Graphs use verification status for node color and distinguish unresolved expansion nodes.
- Export layouts preserve the same terminology and status ordering as the application.

## Accessibility

Controls require visible focus states, descriptive accessible names, keyboard operation, adequate contrast, and reduced-motion behavior. Status icons must include text alternatives.

