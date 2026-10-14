#!/usr/bin/env python3
"""Screen a candidate against the `_Main` listing without spending an attempt.

`tools/try` is the authoritative measurement: it validates the boundary, checks
relocations, writes a report and increments the attempt counter in
`status.json`. This tool does none of that. It exists so that a dozen shapes can
be thrown at a parked function in a few minutes and only the promising ones are
handed to `tools/try`.

What it does:
  * slices the target words straight out of `asm/_Main/text.s` between two
    labels (or, if the end argument is a bare integer, the first N words after
    the start label -- for bodies whose successor is unlabelled);
  * compiles the candidate with exactly the flags `tools/try` uses;
  * runs it under BOTH MWCC 2.4.7 builds, because the two agree on every function
    measured so far and a disagreement is itself worth knowing;
  * prints the leading match, the overall match and the emitted word count.

Usage:
    tools/ab.py <candidate.c> <start label> <end label-or-count>

Environment:
    DUMP=1   print the target and the emitted instructions as well

Per-object flags: the real build applies `src/foo.o: CFLAGS += ...` lines from
the Makefile, so the screening compile applies them too (same lookup as
`tools/try`). Without that, a candidate whose original used e.g.
`-use_lmw_stmw on` scores a false failure. `AB_FLAGS` overrides the lookup for
an experiment that is not yet recorded in the Makefile.

Scores are NOT written to `status.json` and do NOT count as attempts. Nothing is
integrated; there is no relocation check. A score from this tool is a hint, not
a verification -- only `tools/try` can confirm a match.

Note on parsing: the listing prints spaces after commas in operand lists, so a
regex like `r0,r0` matches nothing. Match `r0, r0`.
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
c_file, start_label, end_label = sys.argv[1:4]

ASM_PATH = os.path.join(repo, "asm", "_Main", "text.s")
MAKEFILE_PATH = os.path.join(repo, "Makefile")
PER_OBJECT = re.compile(r"^([^\s:#]+\.o):\s*CFLAGS\s*\+=\s*(.+)$")


def per_object_flags(candidate):
    """Extra MWCC flags recorded for this candidate's object in the Makefile.

    The real build applies `src/foo.o: CFLAGS += ...` lines; keep the screening
    compile byte-for-byte comparable with that, or a function whose original used
    e.g. `-use_lmw_stmw on` scores a false failure.
    """
    override = os.environ.get("AB_FLAGS")
    if override is not None:
        return shlex.split(override)
    obj = os.path.splitext(os.path.normpath(candidate))[0] + ".o"
    with open(MAKEFILE_PATH, encoding="utf-8", errors="replace") as makefile:
        for line in makefile:
            match = PER_OBJECT.match(line)
            if match and os.path.normpath(match.group(1)) == obj:
                return shlex.split(match.group(2).strip())
    return []

# Keep these byte-for-byte identical to tools/try, or scores are not comparable
# with everything already recorded in notes/.
BASE = ["-c", "-O4,p", "-inline", "auto", "-nodefaults", "-proc", "gekko",
        "-fp", "hard", "-fp_contract", "on", "-Cpp_exceptions", "off", "-enum", "int",
        "-warn", "pragmas", "-pragma", "cats off", "-sdata", "0", "-sdata2", "0", "-g",
        "-i", "src", "-I-"]

BUILDS = (("build107(2.6)", "tools/mwcc_compiler/2.6/mwcceppc.exe"),
          ("build108(GC/2.7)", "tools/mwcc_compiler/GC/2.7/mwcceppc.exe"))

env = dict(os.environ)
env["DEVKITPRO"] = env.get("DEVKITPRO") or "/opt/devkitpro"
env["DEVKITPPC"] = env.get("DEVKITPPC") or env["DEVKITPRO"] + "/devkitPPC"
env["PATH"] = (env["DEVKITPPC"] + "/bin:" + env["DEVKITPRO"] + "/tools/bin:" + env.get("PATH", ""))
env["WINE"] = env.get("WINE") or os.path.expanduser("wine")
env["WINEPREFIX"] = env.get("WINEPREFIX") or os.path.expanduser("~/.wine")
env["WINEDEBUG"] = env.get("WINEDEBUG") or "-all"

RE_ASM_REL = re.compile(r"^/\* [0-9A-Fa-f]+ ([0-9A-Fa-f]{8}) \*/\s*(.*)$")
RE_INS = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} ){3}[0-9a-f]{2})\s*(.*)$")


def target_words(start_label, end_label):
    limit = int(end_label) if end_label.isdigit() else None
    out, active = [], False
    for line in open(ASM_PATH, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if line == start_label + ":":
            active = True
            continue
        if active and limit is None and line == end_label + ":":
            break
        if active:
            m = RE_ASM_REL.match(line)
            if m:
                out.append((m.group(1).lower(), m.group(2)))
                if limit is not None and len(out) >= limit:
                    break
    return out


def compile_words(compiler_path, extra=()):
    work = tempfile.mkdtemp(prefix="srab-")
    cand = os.path.join(work, "cand.o")
    cmd = [env["WINE"], compiler_path] + BASE + list(extra) + ["-o", cand, c_file]
    r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        shutil.rmtree(work)
        return None, (r.stdout + r.stderr).strip().splitlines()[-3:]
    dis = subprocess.run([env["DEVKITPPC"] + "/bin/powerpc-eabi-objdump", "-dr", cand],
                         cwd=repo, capture_output=True, text=True).stdout
    shutil.rmtree(work)
    words = []
    for line in dis.splitlines():
        m = RE_INS.match(line)
        if m:
            words.append((m.group(1).lower(), m.group(2).replace(" ", ""), m.group(3)))
    if os.environ.get("DUMP"):
        for w in words:
            print(f"   {w[0]:>4}  {w[1]}  {w[2]}")
    return words, None


def score(cand, targ):
    lead = 0
    for a, b in zip(cand, targ):
        if a[1] != b[0]:
            break
        lead += 1
    overall = sum(1 for a, b in zip(cand, targ) if a[1] == b[0])
    return lead, overall, len(targ)


targ = target_words(start_label, end_label)
if not targ:
    sys.exit(f"no target words between {start_label} and {end_label}")
print(f"target: {start_label}..{end_label}  {len(targ)} words")
if os.environ.get("DUMP"):
    print("--- target ---")
    for w in targ:
        print(f"        {w[0]}  {w[1]}")

extra_flags = per_object_flags(c_file)
if extra_flags:
    print(f"per-object flags: {' '.join(extra_flags)}")

for name, path in BUILDS:
    words, err = compile_words(os.path.join(repo, path), extra_flags)
    if words is None:
        print(f"  {name:20s} COMPILE FAILED: {err}")
        continue
    lead, overall, n = score(words, targ)
    print(f"  {name:20s} {lead}/{n} leading   {overall}/{n} overall   ({len(words)} emitted)")
