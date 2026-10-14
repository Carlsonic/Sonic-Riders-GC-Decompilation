#!/usr/bin/env python3
"""List candidate functions for conversion, with correct function boundaries.

A label only starts a function when the previous instruction is a `blr` and
nothing outside the function branches to it. A label after a `blr` can still be
an internal exit target reached by `beq`/`b` from inside a larger function, and
converting one of those would be wrong.
"""
import argparse, os, re, sys

RE_LABEL = re.compile(r"^(lbl_[0-9A-Fa-f]+):$")
RE_INS_DOL = re.compile(r"^/\* ([0-9A-Fa-f]{8}) ([0-9A-Fa-f]{8}) +(?:[0-9A-Fa-f]{2} ){3}[0-9A-Fa-f]{2} \*/\s*(.*)$")
RE_INS_REL = re.compile(r"^/\* ([0-9A-Fa-f]+) ([0-9A-Fa-f]{8}) \*/\s*(.*)$")
RE_BRANCH = re.compile(r"\b(bl|beq|bne|blt|bgt|ble|bge|beqlr|bnelr|bltlr|bgtlr|blelr|bgelr|b)\s+(lbl_[0-9A-Fa-f]+)")


def load(path):
    labels, insns = {}, []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        m = RE_LABEL.match(line)
        if m:
            labels[m.group(1)] = len(insns)
            continue
        m = RE_INS_DOL.match(line) or RE_INS_REL.match(line)
        if m:
            insns.append((int(m.group(1), 16), m.group(3).strip()))
    return labels, insns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("asm", nargs="?", default="asm/_Main/text.s")
    ap.add_argument("--min", type=int, default=6)
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--calls", type=int, default=0)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--allow-outbound", action="store_true",
                    help="include functions that branch or call outside their own range")
    ap.add_argument("--show", action="store_true", help="print the assembly of each result")
    args = ap.parse_args()

    labels, insns = load(args.asm)
    addr_of = {a: i for i, (a, _) in enumerate(insns)}

    # every branch target, as an instruction index
    targets = {}
    for i, (_, text) in enumerate(insns):
        for m in RE_BRANCH.finditer(text):
            if m.group(2) in labels:
                targets.setdefault(labels[m.group(2)], []).append(i)

    funcs = []
    for name, start in labels.items():
        if start == 0 or "blr" not in insns[start - 1][1]:
            continue
        end = start + 1
        while end < len(insns) and "blr" not in insns[end - 1][1]:
            end += 1
        if end >= len(insns):
            continue
        # end already points one past the closing blr
        # reject if something outside the function branches here
        if any(not (start <= src < end) for src in targets.get(start, [])):
            continue
        body = [t for _, t in insns[start:end]]
        n = len(body)
        if not args.min <= n <= args.max:
            continue
        if any("stwu" in b and "r1" in b for b in body):
            continue
        calls = sum(1 for b in body if b.strip().startswith("bl "))
        if calls > args.calls:
            continue
        # A C call or a tail branch out of the function becomes an R_PPC_REL24
        # relocation the original did not have, which changes the REL even when
        # every instruction matches. Only convert self-contained functions.
        outbound = set()
        for _, text in insns[start:end]:
            for m in RE_BRANCH.finditer(text):
                tgt = m.group(2)
                if tgt in labels and not (start <= labels[tgt] < end):
                    outbound.add(tgt)
        if outbound and not args.allow_outbound:
            continue
        a0, a1 = insns[start][0], insns[end - 1][0]
        funcs.append((n, a1 - a0 + 4, name, a0, start, end))

    print(f"{'insns':>5} {'bytes':>6}  address    function")
    for n, b, name, a, s, e in funcs[: args.limit]:
        print(f"{n:5} {b:6}  0x{a:06X}    {name}")
        if args.show:
            for addr, text in insns[s:e]:
                print(f"          {text}")
    print(f"\n{len(funcs)} candidate(s) between {args.min} and {args.max} instructions, "
          f"frameless, at most {args.calls} call(s), not branched into from outside")


if __name__ == "__main__":
    sys.exit(main())
