#!/usr/bin/env python3
"""Compare a DOL candidate compiled with the project's MWCC options against the
original instruction words in a static (.dol) disassembly listing.

Unlike `tools/compare_function.py`, this handles `@sda21` small-data references.
In a candidate object those load/store instructions carry `disp=0, rA=0`; the
linked listing carries the linker-filled displacement and `rA=13`, so raw word
comparison can never match. This tool therefore requires *exact* word equality
where the candidate has no relocation, and where it has an R_PPC_EMB_SDA21
relocation it normalizes the displacement and the rA field on both sides and
requires opcode+rD plus the relocation symbol to match.

Usage: compare_dol.py <candidate.c> <asm_file> <start_label> <end_label>
"""
import os, re, subprocess, sys, tempfile, shutil

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
c_file, asm_file, start, end = sys.argv[1:5]

work = tempfile.mkdtemp(prefix="srdol-")
env = dict(os.environ)
env["DEVKITPRO"] = env.get("DEVKITPRO") or "/opt/devkitpro"
env["DEVKITPPC"] = env.get("DEVKITPPC") or env["DEVKITPRO"] + "/devkitPPC"
env["PATH"] = (env["DEVKITPPC"] + "/bin:" + env["DEVKITPRO"] +
               "/tools/bin:" + env.get("PATH", ""))
env["WINE"] = env.get("WINE") or os.path.expanduser("wine")
env["WINEPREFIX"] = env.get("WINEPREFIX") or os.path.expanduser("~/.wine")
env["WINEDEBUG"] = env.get("WINEDEBUG") or "-all"

# Same flags as the DOL objects in the Makefile (no -sdata/-sdata2: the DOL uses
# the default small-data threshold 8, so small globals land in .sbss/@sda21).
cmd = [env["WINE"], "tools/mwcc_compiler/2.6/mwcceppc.exe", "-c",
       "-O4,p", "-inline", "auto", "-nodefaults", "-proc", "gekko",
       "-fp", "hard", "-fp_contract", "on", "-Cpp_exceptions", "off", "-enum", "int",
       "-warn", "pragmas", "-pragma", "cats off",
       "-i", "src", "-I-", "-o", os.path.join(work, "cand.o"), c_file]
r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True)
if r.returncode != 0:
    print("COMPILE FAILED\n" + r.stdout + r.stderr)
    shutil.rmtree(work); sys.exit(1)


def target_instructions():
    lines = open(os.path.join(repo, asm_file), encoding="utf-8",
                 errors="replace").readlines()
    start_idx = next(i for i, l in enumerate(lines)
                     if l.strip().startswith(start + ":"))
    end_idx = next(i for i in range(start_idx + 1, len(lines))
                   if lines[i].strip().startswith(end + ":"))
    insn_re = re.compile(r"/\* [0-9A-Fa-f]{8} [0-9A-Fa-f]{8}  "
                         r"(..) (..) (..) (..) \*/(.*)")
    sda_re = re.compile(r"([\w.]+)@sda21")
    out = []
    for l in lines[start_idx:end_idx]:
        m = insn_re.search(l)
        if not m:
            continue
        word = int(m.group(1) + m.group(2) + m.group(3) + m.group(4), 16)
        text = m.group(5).strip()
        sm = sda_re.search(text)
        out.append((word, sm.group(1) if sm else None, text))
    return out


def candidate_instructions():
    dis = subprocess.run([env["DEVKITPPC"] + "/bin/powerpc-eabi-objdump", "-dr",
                          os.path.join(work, "cand.o")],
                         cwd=repo, capture_output=True, text=True).stdout
    reloc_re = re.compile(r"^\s*([0-9a-f]+):\s+R_PPC_\w+\s+(\S+)")
    insn_re = re.compile(r"^\s*([0-9a-f]+):\s+"
                         r"((?:[0-9a-f]{2}\s+){3}[0-9a-f]{2})\s+(.*)$")
    relocs = {}
    for l in dis.splitlines():
        m = reloc_re.match(l)
        if m:
            relocs[int(m.group(1), 16)] = m.group(2)
    insns = []
    for l in dis.splitlines():
        m = insn_re.match(l)
        if m:
            word = int(m.group(2).replace(" ", ""), 16)
            insns.append((int(m.group(1), 16), word,
                          relocs.get(int(m.group(1), 16)),
                          m.group(3).strip()))
    return insns


def main():
    target = target_instructions()
    cand = candidate_instructions()
    if len(target) != len(cand):
        print(f"instruction count mismatch: target {len(target)} "
              f"candidate {len(cand)}")
    n = min(len(target), len(cand))
    ok = 0
    div = []
    for i in range(n):
        t_word, t_sym, t_text = target[i]
        c_off, c_word, c_sym, c_text = cand[i]
        if c_sym is None:
            match = c_word == t_word
        else:
            # sda21: linker writes the displacement and rewrites rA (0 -> 13).
            nrm = lambda w: (w & 0xFFE00000) | 0x000D0000
            match = nrm(c_word) == nrm(t_word) and c_sym == t_sym
        if match:
            ok += 1
        else:
            div.append((i, t_word, t_sym, t_text, c_off, c_word, c_sym, c_text))
    print(f"match {ok}/{len(target)}")
    for (i, tw, ts, tt, co, cw, cs, ct) in div:
        print(f"  [+0x{i*4:04x}]")
        print(f"    target   : {tw:08X} {'@'+ts if ts else ''}  {tt}")
        print(f"    candidate: {cw:08X} {'@'+cs if cs else ''}  {ct}")
    shutil.rmtree(work)
    sys.exit(0 if ok == len(target) else 1)


if __name__ == "__main__":
    main()