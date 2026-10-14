#!/usr/bin/env python3
"""Compare a compiled candidate object against the original instruction words
recorded in the comments of the disassembly listing."""
import os, re, subprocess, sys, tempfile, shutil

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
c_file, asm_file, start, end = sys.argv[1:5]
extra_flags = sys.argv[5] if len(sys.argv) > 5 else ""

work = tempfile.mkdtemp(prefix="srdol-")
env = dict(os.environ)
env["DEVKITPRO"] = env.get("DEVKITPRO") or "/opt/devkitpro"
env["DEVKITPPC"] = env.get("DEVKITPPC") or env["DEVKITPRO"] + "/devkitPPC"
env["PATH"] = (env["DEVKITPPC"] + "/bin:" + env["DEVKITPRO"] +
               "/tools/bin:" + env.get("PATH", ""))
env["WINE"] = env.get("WINE") or os.path.expanduser("wine")
env["WINEPREFIX"] = env.get("WINEPREFIX") or os.path.expanduser("~/.wine")
env["WINEDEBUG"] = env.get("WINEDEBUG") or "-all"

cmd = [env["WINE"], "tools/mwcc_compiler/2.6/mwcceppc.exe", "-c",
       "-O4,p", "-inline", "auto", "-nodefaults", "-proc", "gekko",
       "-fp", "hard", "-fp_contract", "on", "-Cpp_exceptions", "off", "-enum", "int",
       "-warn", "pragmas", "-pragma", "cats off",
       "-sdata", "0", "-sdata2", "0", "-g"]
if extra_flags:
    cmd += extra_flags.split()
cmd += ["-i", "src", "-I-", "-o", os.path.join(work, "cand.o"), c_file]
r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True)
if r.returncode != 0:
    print("COMPILE FAILED\n" + r.stdout + r.stderr)
    shutil.rmtree(work); sys.exit(1)

dis = subprocess.run([env["DEVKITPPC"] + "/bin/powerpc-eabi-objdump", "-dr",
                      os.path.join(work, "cand.o")],
                     cwd=repo, capture_output=True, text=True).stdout

# Two comment layouts exist. The static DOL writes the address, the file offset
# and the four bytes; _Main writes the address and the word directly.
RE_ASM_DOL = re.compile(r"^/\* [0-9A-Fa-f]+ [0-9A-Fa-f]+\s+"
                        r"([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{2}) ([0-9A-Fa-f]{2})"
                        r" \*/\s*(.*)$")
RE_ASM_REL = re.compile(r"^/\* [0-9A-Fa-f]+ ([0-9A-Fa-f]{8}) \*/\s*(.*)$")
RE_INS = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} ){3}[0-9a-f]{2})\s*(.*)$")

def target_words(path, start_label, end_label):
    out, active = [], False
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line == start_label + ":":
            active = True; continue
        if line == end_label + ":":
            break
        if active:
            m = RE_ASM_DOL.match(line)
            if m:
                out.append(("".join(m.group(i) for i in (1, 2, 3, 4)).lower(), m.group(5)))
                continue
            m = RE_ASM_REL.match(line)
            if m:
                out.append((m.group(1).lower(), m.group(2)))
    return out

def candidate_words(dump):
    out, active = [], False
    for line in dump.splitlines():
        if line.startswith("Disassembly of section .text:"):
            active = True; continue
        if active and line.startswith("Disassembly of section "):
            break
        if active:
            m = RE_INS.match(line)
            if m:
                out.append((m.group(2).replace(" ", "").lower(), m.group(3).strip()))
    return out

RE_SYM = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)@(ha|l)")

def target_symbols(path, start_label, end_label):
    """Relocation symbols of the target, in instruction order.

    Two kinds of reference exist in the listing and both must be counted:

      * data accesses, written as ``sym@ha`` / ``sym@l`` and relocating to
        ``R_PPC_ADDR16_HA`` / ``R_PPC_ADDR16_LO`` -- two entries per access;
      * calls, written as ``bl sym`` with no annotation, relocating to a single
        ``R_PPC_REL24``.

    Counting only the annotated form misses every ``bl`` and reports a false
    mismatch against a correct candidate.
    """
    out, active = [], False
    inner_labels = set()
    span_lines = []
    capture = False
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line == start_label + ":":
            capture = True; continue
        if line == end_label + ":":
            break
        if capture:
            span_lines.append(line)
            if line.endswith(":") and not line.startswith("/*"):
                inner_labels.add(line[:-1])

    for line in span_lines:
        if not (RE_ASM_DOL.match(line) or RE_ASM_REL.match(line)):
            continue
        found = False
        for m in RE_SYM.finditer(line):
            out.append(m.group(1))
            found = True
        if not found:
            # Plain call. ``bl\s`` excludes blt/ble/blr, which are not calls.
            m = re.search(r"\sbl\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line)
            # A call to a label inside the span is resolved by the assembler and
            # carries no relocation; only cross-boundary calls do.
            if m and m.group(1) not in inner_labels:
                out.append(m.group(1))
    return out

def candidate_symbols(dump, object_path):
    """Relocation symbols in instruction order, ignoring the debug sections.

    objdump reports the byte offset of the patched field, so relocations are
    indexed by the instruction word they belong to.
    """
    relocs, active = {}, False
    for line in dump.splitlines():
        if line.startswith("Disassembly of section "):
            active = line.startswith("Disassembly of section .text:")
            if not active and ".rela." not in line:
                continue
        if not active:
            continue
        m = re.match(r"^\s*([0-9a-f]+):\s+(R_PPC_\S+)\s+(\S+)\s*$", line)
        if m:
            word = int(m.group(1), 16) // 4 * 4
            relocs.setdefault(word, []).append(m.group(3))
    ordered = []
    for word in sorted(relocs):
        ordered += relocs[word]
    return ordered

t = target_words(os.path.join(repo, asm_file), start, end)
c = candidate_words(dis)
tw, cw = len(t), len(c)
print(f"target instructions: {tw}   candidate instructions: {cw}")

lead = 0
for i in range(min(tw, cw)):
    if t[i][0] != c[i][0]:
        break
    lead = i + 1
total = sum(1 for i in range(min(tw, cw)) if t[i][0] == c[i][0])
print(f"identical leading instructions: {lead} / {tw}   (identical overall: {total} / {tw})")
print(f"first divergence at instruction: {lead + 1}")
print()
print("--- target, from divergence ---")
for w, txt in t[lead:lead + 14]:
    print(f"  {w}  {txt}")
print("--- candidate, from divergence ---")
for w, txt in c[lead:lead + 14]:
    print(f"  {w}  {txt}")

# Words alone are not enough. Two candidates can encode identical instructions and
# still attach the relocations to different symbols, which writes the wrong
# globals and only shows up as a REL checksum failure after splicing.
ts = target_symbols(os.path.join(repo, asm_file), start, end)
cs = candidate_symbols(dis, os.path.join(work, "cand.o"))
print()
if not ts and not cs:
    print("relocations: none on either side")
elif ts == cs:
    print(f"relocations: {len(ts)} symbol reference(s) match in order: {' '.join(ts)}")
else:
    print("relocation MISMATCH - the words can be identical and this still be wrong:")
    print(f"  target:    {' '.join(ts) if ts else '(none)'}")
    print(f"  candidate: {' '.join(cs) if cs else '(none)'}")
    print("  do not splice: check @ha/@l symbols with objdump -dr against the listing")
shutil.rmtree(work)
