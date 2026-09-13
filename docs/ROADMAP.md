# Internal Build-and-Test Order

Note: there is a single shipping milestone (the full finished product — see DECISIONS_LOG.md). This roadmap is **not** a phased release plan; it is purely the order in which the solo builder should construct and verify each layer, so that no layer is ever tested against fake/nonexistent input from a layer that doesn't exist yet.

---

## Stage 1 — Foundation
- **Layer 1** (Ingestion): GitHub link → clone → filter junk → clean file tree
- **Layer 9** (Storage/Caching skeleton): basic DB setup so every later stage has somewhere to write results while testing
- **Layer 10** (Security/Sandboxing): build alongside Layer 1 — sandboxing needs to exist before real untrusted code ever gets processed by anything downstream

## Stage 2 — Structural Backbone
- **Layer 2**: build ONE language parser fully first (builder's fastest language) → verify clean output shape → replicate the pattern for the remaining 8 languages one at a time
- **Layer 3**: git history extraction — independent of Layer 2, can be built in parallel

## Stage 3 — Understanding Layer
- **Layer 4** (Segmentation): depends on Layer 2 output existing for at least a few languages to test against
- **Layer 5** (RAG engine): depends on Layer 1 + Layer 2 output (chunking/embedding); can be built in parallel with Layer 4 since neither depends on the other

## Stage 4 — Reasoning Core
- **Layer 6** (Sequence Reasoning): depends on Layer 2 (graph) + Layer 3 (history) + Layer 4 (segments) all existing first. Build its four internal stages in order: candidate generation → graph validation → confidence scoring → narration

## Stage 5 — Integration
- **Layer 7** (Synthesis): depends on Layers 4, 5, 6 all producing real output to combine
- **Layer 8** (Output Formatting): depends on Layer 7 being stable, since it only presents Layer 7's data
- **Layer 11** (Job Queue/Progress): wire in once there's a real multi-layer pipeline worth queuing

## Stage 6 — Hardening
- Layer 9 fully fleshed out: consent flows, proper caching (repo URL + commit hash keying), cleanup routines, backups
- Remaining Layer 2 language parsers completed if not already done
- Edge case handling across all layers: large repos, malformed input, missing git history, unsupported languages, uncategorized files
- Auth, billing, monitoring, analytics, CI/CD wired in

---

## Testing approach throughout
- Primary test suite: builder's own 13-15 real repos, used as ground truth for whether Layer 6's guessed sequences are "good enough"
- Automated tests specifically for Layer 2 parsers (most mechanical/repetitive, easiest to silently break, same pattern repeated 9 times across languages)
- Everything else: manual verification as each stage completes
