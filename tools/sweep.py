#!/usr/bin/env python3
"""Compile and score candidate variants of one function.

Usage:
    sweep.py <asm file> <start label> <end label> <variants dir> [--jobs N]

Each variant gets an isolated temporary output directory. MWCC processes may
share a warmed Wine prefix and wineserver.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import os
import re
import shutil
import subprocess
import tempfile

RE_ASM_DOL = re.compile(
    r"^/\* [0-9A-Fa-f]+ [0-9A-Fa-f]+\s+"
    r"([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{2})"
    r" \*/\s*(.*)$")
RE_ASM_REL = re.compile(r"^/\* [0-9A-Fa-f]+ ([0-9A-Fa-f]{8}) \*/\s*(.*)$")
RE_INS = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} ){3}[0-9a-f]{2})\s*(.*)$")
RE_SYM = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)@(ha|l)")
RE_RELOC = re.compile(r"^\s*([0-9a-f]+):\s+(R_PPC_\S+)\s+(\S+)\s*$")


def target_words(path, start_label, end_label):
    words, active = [], False
    start_found = end_found = False
    with open(path, encoding="utf-8", errors="replace") as source:
        for line in source:
            line = line.rstrip("\n")
            if line == start_label + ":":
                active = start_found = True
                continue
            if active and line == end_label + ":":
                end_found = True
                break
            if active:
                match = RE_ASM_DOL.match(line)
                if match:
                    words.append(("".join(match.group(i) for i in (1, 2, 3, 4)).lower(),
                                  match.group(5)))
                    continue
                match = RE_ASM_REL.match(line)
                if match:
                    words.append((match.group(1).lower(), match.group(2)))
    if not start_found or not end_found:
        raise ValueError(f"missing function boundary: {start_label} -> {end_label}")
    return words


def target_symbols(path, start_label, end_label):
    symbols, active = [], False
    with open(path, encoding="utf-8", errors="replace") as source:
        for line in source:
            line = line.rstrip("\n")
            if line == start_label + ":":
                active = True
                continue
            if active and line == end_label + ":":
                break
            if active and (RE_ASM_DOL.match(line) or RE_ASM_REL.match(line)):
                symbols.extend(match.group(1) for match in RE_SYM.finditer(line))
    return symbols


def candidate_words(dump):
    words, active = [], False
    for line in dump.splitlines():
        if line.startswith("Disassembly of section .text:"):
            active = True
            continue
        if active and line.startswith("Disassembly of section "):
            break
        if active:
            match = RE_INS.match(line)
            if match:
                words.append((match.group(2).replace(" ", "").lower(),
                              match.group(3).strip()))
    return words


def candidate_symbols(dump):
    relocs, active = {}, False
    for line in dump.splitlines():
        if line.startswith("Disassembly of section "):
            active = line.startswith("Disassembly of section .text:")
            if not active and ".rela." not in line:
                continue
        if not active:
            continue
        match = RE_RELOC.match(line)
        if match:
            word = int(match.group(1), 16) // 4 * 4
            relocs.setdefault(word, []).append(match.group(3))
    return [symbol for word in sorted(relocs) for symbol in relocs[word]]


def compile_and_score(job):
    name, vdir, repo, env, extra_flags, target, target_relocs = job
    source_path = os.path.join(vdir, name)
    work = tempfile.mkdtemp(prefix="srsweep-")
    obj = os.path.join(work, "candidate.o")
    objdump = os.path.join(env["DEVKITPPC"], "bin", "powerpc-eabi-objdump")
    cmd = [env["WINE"], "tools/mwcc_compiler/2.6/mwcceppc.exe", "-c",
           "-O4,p", "-inline", "auto", "-nodefaults", "-proc", "gekko",
           "-fp", "hard", "-fp_contract", "on", "-Cpp_exceptions", "off",
           "-enum", "int", "-warn", "pragmas", "-pragma", "cats off",
           "-sdata", "0", "-sdata2", "0", "-g"]
    if extra_flags:
        cmd.extend(extra_flags.split())
    cmd.extend(["-i", "src", "-I-", "-o", obj, source_path])
    try:
        result = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True)
        if result.returncode:
            detail = (result.stdout + result.stderr).strip().splitlines()
            return name, "COMPILE FAIL", detail[0][:60] if detail else "", "", None, -1, False

        result = subprocess.run([objdump, "-dr", obj], cwd=repo,
                                capture_output=True, text=True)
        if result.returncode:
            detail = (result.stdout + result.stderr).strip().splitlines()
            return name, "OBJDUMP FAIL", detail[0][:60] if detail else "", "", None, -1, False

        words = candidate_words(result.stdout)
        relocations = candidate_symbols(result.stdout)
        leading = 0
        for index in range(min(len(target), len(words))):
            if target[index][0] != words[index][0]:
                break
            leading = index + 1
        matched = sum(target[i][0] == words[i][0]
                      for i in range(min(len(target), len(words))))
        exact = (matched == len(target) and len(words) == len(target)
                 and relocations == target_relocs)
        score = f"{leading}/{len(target)} lead, {matched}/{len(target)} words, {len(words)} emitted"
        reloc = "reloc OK" if relocations == target_relocs else f"reloc {relocations}"
        return name, score, reloc, "EXACT" if exact else "", words, matched, exact
    finally:
        shutil.rmtree(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asm_file")
    parser.add_argument("start")
    parser.add_argument("end")
    parser.add_argument("variants_dir")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1),
                        help="parallel MWCC workers (default: up to 4)")
    parser.add_argument("--dumps", action="store_true",
                        help="print disassembly for every variant")
    parser.add_argument("--flags", default="",
                        help="additional MWCC flags for every variant")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    asm_file = args.asm_file if os.path.isabs(args.asm_file) else os.path.join(repo, args.asm_file)
    vdir = args.variants_dir if os.path.isabs(args.variants_dir) else os.path.join(repo, args.variants_dir)
    env = dict(os.environ)
    env["DEVKITPRO"] = env.get("DEVKITPRO") or "/opt/devkitpro"
    env["DEVKITPPC"] = env.get("DEVKITPPC") or env["DEVKITPRO"] + "/devkitPPC"
    env["PATH"] = (env["DEVKITPPC"] + "/bin:" + env["DEVKITPRO"] +
                   "/tools/bin:" + env.get("PATH", ""))
    env["WINE"] = env.get("WINE") or os.path.expanduser("wine")
    env["WINEPREFIX"] = env.get("WINEPREFIX") or os.path.expanduser("~/.wine")
    env["WINEDEBUG"] = env.get("WINEDEBUG") or "-all"

    try:
        target = target_words(asm_file, args.start, args.end)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if not target:
        parser.error(f"no target instructions found between {args.start} and {args.end}")
    target_relocs = target_symbols(asm_file, args.start, args.end)
    variants = sorted(name for name in os.listdir(vdir) if name.endswith(".c"))
    print(f"target {args.start}: {len(target)} instructions, "
          f"symbols: {' '.join(target_relocs) or '(none)'}")
    print()

    jobs = [(name, vdir, repo, env, args.flags, target, target_relocs)
            for name in variants]
    with ProcessPoolExecutor(max_workers=min(args.jobs, len(jobs) or 1)) as pool:
        rows = list(pool.map(compile_and_score, jobs))

    best = max((row for row in rows if row[5] >= 0),
               key=lambda row: (row[5], row[6]), default=None)
    for name, score, reloc, tag, dump, _, _ in rows:
        print(f"{name:28s} {score:42s} {reloc}"
              f"{'  <-- ' + tag if tag else ''}")
        if dump and args.dumps:
            for word, text in dump:
                print(f"      {word}  {text}")

    print()
    if best:
        print(f"best: {best[0]} ({best[5]}/{len(target)} words)")
        if not best[6]:
            print("\n--- target ---")
            for word, text in target:
                print(f"  {word}  {text}")
            print(f"--- {best[0]} ---")
            for word, text in best[4]:
                print(f"  {word}  {text}")


if __name__ == "__main__":
    main()
