# How was it achieved

This document summarizes the actual process used to produce instruction-exact matches for this project.

## Environment
- Compiler: Metrowerks CodeWarrior PowerPC for GameCube 2.6 (MWCC GC 2.6). This is not MWCC for Wii 2.6 — different codegen.
- MWCC GC 2.6 is a Windows EXE; on non-Windows systems it was run via Wine where needed.
- Target: Sonic Riders (USA, GXEE8P, rev 00), DOL sha1 e90a13504974b917a675d59f07014e0e817c5e5d.
- Base: assembly listing, _Main.map, _Main.rel from https://github.com/doldecomp/sonicriders.

## Matching pipeline
1. **Find true boundaries.** Start at `stwu` (prologue). End at `blr` before next `stwu`. The map often points to internal labels or epilogue blocks (e.g. `mr r3,r30|r31` + restore + blr). When successor has no label, use `--end-marker <address>` (instruction address from listing).
2. **Write minimal C.** Avoid guessing high-level structure too early; match by small changes.
3. **Compare automatically.** `tools/try` compiles with MWCC GC 2.6, disassembles the .o and compares against the original span (words + relocations). `tools/compare_function.py` does the core comparison. `tools/ab.py`/`tools/sweep.py` help screen candidates.
4. **Iterate by levers.** Only one change at a time. Proven levers: `extern u8 *` for pointer variables read via `lis/addi/lwz`; local declaration order; `const` placement; casts preserving `clrlwi` (e.g. `& 0xff`); `-use_lmw_stmw on` for certain functions; branch order with signed checks; careful with tail branches.
5. **Integrate only on exact match.** `tools/try --integrate` writes to `MAIN_FUNCS` only when instructions and relocations match exactly. Then run full checksum build (dol + rel OK).
6. **Splice.** `tools/splice_main_text.sh`/`tools/replace_main_text.sh` splice matched bodies into the monolithic listing.

## Key observations
- Map is conservative in a misleading way: internal labels split spans. Use end-marker when needed (e.g. `lbl_000F7EB8` → end at `000F7EF0`).
- Epilogues are not functions. Look for `stwu` to identify real function starts.
- Pointer variable semantics matter: materialization `lis/addi/lwz 0(r)` requires `extern u8 *sym` (value read), not array folding.

## Minimal workflow summary
1. Get doldecomp/sonicriders files + baserom.dol + MWCC GC 2.6.
2. Pick symbol, determine true start/end (use end-marker if ambiguous).
3. `tools/try <sym> src/<sym>.c [--end-marker <addr>]` until exact (≤12 attempts).
4. `tools/try <sym> src/<sym>.c [--end-marker <addr>] --integrate`, verify full build.

This is the exact process used; no literal asm or full C was copied. Descriptions focus on purpose/levers only.
