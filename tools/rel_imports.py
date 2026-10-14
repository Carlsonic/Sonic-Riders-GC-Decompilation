#!/usr/bin/env python3
"""Analyze the REL->DOL import graph of _Main.rel (Metrowerks RSO).

Answers "which DOL function does the REL call, and from where" statically,
from the relocation streams -- no debugger / emulator needed.

Usage:
  rel_imports.py                 # summary + top DOL targets + wanted call sites
  rel_imports.py 0x8009BEF4 ...  # show call sites for specific DOL targets

REL format facts (from tools/elf2rel.c):
  header: moduleId=1, formatVersion=3, sectionTableOffset points to 14 x 8-byte
  entries (offset|execbit, size). reloc table offset in header +0x24.
  import table: pairs (moduleId, relocStreamStart).
  reloc entry: u16 offsetDelta, u8 type (202=SEC switch, 203=END), u8 symSection,
  u32 symAddr. patched file offset = sec[secId].offset + accumulated delta.
  DOL module = moduleId 0; its stream carries absolute 0x80xxxxxx addresses.
"""
import re
import struct
import sys
from collections import defaultdict

RELPATH = "_Main.rel"
MAPPATH = "_Main.map"

TYPES = {1: "ADDR32", 2: "ADDR24", 3: "ADDR16", 4: "ADDR16_LO", 5: "ADDR16_HI",
         6: "ADDR16_HA", 7: "ADDR14", 8: "ADDR14_BRTAKEN", 9: "ADDR14_BRNTAKEN",
         10: "REL24", 11: "REL14", 202: "SECTION", 203: "END"}

DOL_TEXT_START = 0x80003100
DOL_TEXT_END = 0x800E2F20


def load_labels(path):
    labels = []
    pat = re.compile(r"lbl_([0-9A-Fa-f]{8})")
    with open(path, "r", errors="replace") as f:
        for line in f:
            m = pat.search(line)
            if m:
                off = int(m.group(1), 16)
                labels.append((off, "lbl_%08X" % off))
    labels.sort()
    return labels


def nearest(labels, off):
    prev = None
    for o, n in labels:
        if o > off:
            break
        prev = (o, n)
    if prev is None:
        return "<0x%X before first>" % off
    o, n = prev
    return n if off == o else "%s+0x%X" % (n, off - o)


def parse_stream(d, start, end, secs):
    """Return list of (type, relOffsetInModule, symAddr)."""
    out = []
    pat_sec = 0
    prev_off = 0
    pos = start
    while pos + 8 <= end:
        rel_delta, rtype, rsec, symaddr = struct.unpack_from(">HBBI", d, pos)
        pos += 8
        if rtype == 203:  # END
            break
        if rtype == 202:  # SECTION change
            pat_sec = rsec
            prev_off = 0
            continue
        patch_off = prev_off + rel_delta
        try:
            rel_off = secs[pat_sec][0] + patch_off
        except IndexError:
            rel_off = patch_off
        out.append((rtype, rel_off, symaddr))
        prev_off = patch_off
    return out


def main():
    d = open(RELPATH, "rb").read()
    seccnt = struct.unpack_from(">I", d, 0x0C)[0]
    sectab = struct.unpack_from(">I", d, 0x10)[0]
    imp_off = struct.unpack_from(">I", d, 0x28)[0]
    imp_sz = struct.unpack_from(">I", d, 0x2C)[0]
    secs = []
    for i in range(seccnt):
        o, sz = struct.unpack_from(">II", d, sectab + i * 8)
        secs.append((o & 0xFFFFFFFE, o & 1, sz))

    labels = load_labels(MAPPATH)
    want = [int(a, 0) for a in sys.argv[1:]] if len(sys.argv) > 1 else []

    # import table: pairs (moduleId, relocStreamStart)
    streams = []
    for i in range(imp_sz // 8):
        mid, soff = struct.unpack_from(">II", d, imp_off + i * 8)
        streams.append((mid, soff))

    dol_recs = []
    for mid, start in streams:
        pos = start
        end = len(d)
        while pos + 8 <= len(d):
            _, rtype, _, _ = struct.unpack_from(">HBBI", d, pos)
            if rtype == 203:
                end = pos
                break
            pos += 8
        recs = parse_stream(d, start, end, secs)
        is_dol = any(a >= 0x80000000 for _, _, a in recs)
        print("moduleId=%d stream 0x%X..0x%X: %d relocs, DOL-symbols=%s"
              % (mid, start, end, len(recs), is_dol))
        if is_dol:
            dol_recs = recs

    by_target = defaultdict(list)
    for rtype, rel_off, symaddr in dol_recs:
        if DOL_TEXT_START <= symaddr <= DOL_TEXT_END:
            by_target[symaddr].append((rtype, rel_off))

    if want:
        for target in want:
            refs = by_target.get(target)
            if not refs:
                print("\n0x%X: no DOL-.text relocations" % target)
                continue
            print("\n== 0x%X: %d relocs ==" % (target, len(refs)))
            for rtype, rel_off in sorted(refs, key=lambda x: x[1])[:60]:
                print("  REL+0x%-6X %-8s %s" %
                      (rel_off, TYPES.get(rtype), nearest(labels, rel_off)))
        return

    print("\n== %d distinct DOL .text functions called by the REL (count descending) =="
          % len(by_target))
    for target, refs in sorted(by_target.items(),
                               key=lambda kv: (-len(kv[1]), kv[0])):
        n24 = sum(1 for t, _ in refs if t == 10)
        first = nearest(labels, sorted(ro for _, ro in refs)[0])
        print("%-12s calls=%-4d  first site: %s" %
              ("0x%08X" % target, n24, first))


if __name__ == "__main__":
    main()