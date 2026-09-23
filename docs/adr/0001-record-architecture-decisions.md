# ADR 0001: Record Architecture Decisions

- Status: accepted
- Date: 2026-09-22

## Context

candid is growing one feature batch at a time, with multiple people (and
agents) touching the codebase. Design rationale was living in chat history
and commit messages, which is unsearchable and evaporates. We need a durable,
low-ceremony way to record *why* a significant technical decision was made,
so future contributors can understand and challenge it instead of
re-litigating it.

## Decision

We will record significant architecture decisions as Architecture Decision
Records (ADRs) in `docs/adr/`:

- One file per decision, named `NNNN-short-title.md` with a sequential
  number (zero-padded to four digits), starting at 0001.
- Each record follows `docs/adr/TEMPLATE.md`
  (status, context, decision, consequences).
- Status is one of: `proposed`, `accepted`, `deprecated`, `superseded by NNNN`.
- ADRs are proposed as part of a pull request when the PR makes or
  reverses a significant decision: module boundaries, data formats, security
  model, dependency policy, testing strategy, release process.
- Trivial or obviously-reversible choices (naming, formatting, small
  refactors) do not need an ADR; use the PR description.

## Consequences

- Positive: rationale survives the people who made it; new contributors can
  read `docs/adr/` to learn the project's principles in an afternoon.
- Positive: "supersede, don't delete" keeps the history honest; a reversed
  decision stays visible with a pointer to its replacement.
- Negative: small overhead per significant decision (one short markdown
  file). Mitigated by keeping the template minimal and skipping ADRs for
  trivial choices.
- Neutral: ADR numbers are append-only; gaps from rejected proposals are
  fine and need no renumbering.
