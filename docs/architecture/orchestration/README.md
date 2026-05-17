# Architectural orchestration

How WormBase's major structural decisions were planned and executed.
These notes document the "why" and the "how" behind multi-package
refactors, decomposition portfolios, and other cross-cutting
architectural shifts.

For the day-to-day architectural surface the decompositions produced,
see [`../../ARCHITECTURE.md`](../../../ARCHITECTURE.md). For the
discrete decisions captured along the way, see
[`../decisions/`](../decisions/).

## Index

- [worm-decomposition.md](worm-decomposition.md) — Splitting the
  original god-object hub into five named-actor worms-as-packages, plus
  consolidated governance, on a stable runtime hub.
