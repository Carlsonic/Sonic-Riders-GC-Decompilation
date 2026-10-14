# Methodology

Goal: produce instruction/relocation identical C (matching) for **Metrowerks CodeWarrior PowerPC for GameCube 2.6 (MWCC GC 2.6)**. Note: this is different from MWCC for Wii 2.6.

## Setup
- asm listing + map/rel from https://github.com/doldecomp/sonicriders
- baserom.dol (USA GXEE8P, sha1 e90a13504974b917a675d59f07014e0e817c5e5d)
- **MWCC GC 2.6** toolchain (Wine optional, depending on platform); do not use MWCC Wii 2.6

## Loop
1. Pick target (from FUNCTION_INDEX or asm). Find true boundaries (start at `stwu`, end at `blr` before next `stwu`). Don't trust the map blindly.
2. Write minimal C; compare: `tools/try <sym> src/<sym>.c [--end-marker <addr>]`
3. Change one thing, re-run. Stop when stuck (try <= 12). Record levers.
4. `--integrate` only on exact match. Add to MAIN_FUNCS, run full checksum build (dol + rel OK).
5. Share findings by updating index/notes (no literal game asm dumps).

## Practical rules
- `extern u8 *lbl_10087E78` style for pointer variables (not `extern u8 lbl_10087E78[]` when read as value)
- Local var declaration order matters for register assignment
- `const` on globals affects hoisting
- `-use_lmw_stmw on` appears for some functions
- Redundant casts (`& 0xff`) can force `clrlwi`
- Map trap 1: internal label inside function → span too short in effect? Or the other way; use end-marker. Also span can end in `blr` but cover only an epilogue.
- Map trap 2: labels that are epilogues (start with `mr r3,r30/r31`, end with frame restore) — they are NOT functions
- `if (idx < 0)` arm order can invert the layout relative to MWCC
- Watch for tail branches (`b`, `bctr`) — may indicate shared tail inside the same function

## When stuck
- Try different declaration orders
- Try `#pragma scheduling off`, `peephole off` (flag via --flags or Makefile per-object)
- Check if caller-saved registers force different allocation
- Ensure the end marker matches the successor's instruction address (e.g. `/* 000F7EF0 ... */`) when no label
