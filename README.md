# Sonic Riders GC Decompilation — Tooling & Methodology

This repository provides the decompilation tooling, methodology, and a function index
for the GameCube release of **Sonic Riders (USA)** (`GXEE8P`, rev 00).

The focus is to produce C that matches the original exactly (instruction-for-instruction, relocations correct)
using the compiler used in this build: **MWCC GC 2.6**.

> **Important:** This repository does **not** contain game ROMs, ISO images, extracted game assets,
> the original assembly listing, or generated build artifacts (`.dol`, `.rel`, `.map`, `.plf`).

## Requirements

1. A clean DOL of Sonic Riders USA (`sha1: e90a13504974b917a675d59f07014e0e817c5e5d`) placed at `./baserom.dol`.
2. The assembly listing (`asm/_Main/text.s`) and the linked map/rel (`_Main.map`, `_Main.rel`)
   from the [doldecomp/sonicriders](https://github.com/doldecomp/sonicriders) repository.
3. MWCC GC 2.6 toolchain. Place it in a standard devkitPro layout (`tools/mwcc_compiler/GC/2.6/...`)
   or set `DEVKITPRO`/`DEVKITPPC` as appropriate. Set `WINE` to your Wine binary (falls back to `wine`).
4. `make`, `python3`, standard Unix tools.

## Workflow

See `docs/how_was_it_achieved.md` and `METHODOLOGY.md`.

## Legal & Provenance

- The assembly listing is a disassembly of the game's binary and comes from
  [doldecomp/sonicriders](https://github.com/doldecomp/sonicriders). None of those upstream source
  files are redistributed here.
- The scripts in `tools/` were written for this matching workflow. `elf2dol.c`/`elf2rel.c` are not
  distributed; use the ones from upstream or your own build tools.
- No game files, assets, or literal game code in C/asm are included. This repo contains only
  tooling, methodology and metadata (addresses, sizes, signatures, status, levers).

## Attribution

Compiler: Metrowerks CodeWarrior PowerPC for GameCube 2.6 (MWCC GC 2.6). Do not confuse with MWCC Wii 2.6.
