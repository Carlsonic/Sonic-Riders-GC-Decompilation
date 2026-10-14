#!/bin/sh
# Translate a compiled object's .text into inline assembler for the monolithic
# disassembly, preserving the relocations the REL needs.
set -eu

object_file=$1
output_file=$2

mkdir -p "$(dirname "$output_file")"

"${DEVKITPPC:?}/bin/powerpc-eabi-objdump" -dr "$object_file" | awk -v output="$output_file" '
function hex_value(text,    i, digit, result) {
    result = 0
    for (i = 1; i <= length(text); i++) {
        digit = index("0123456789abcdef", tolower(substr(text, i, 1))) - 1
        if (digit < 0 || digit > 15) {
            return -1
        }
        result = result * 16 + digit
    }
    return result
}
function reg(word, first_bit,    i, result, bit) {
    # PowerPC register fields are numbered from the most significant bit:
    # rD occupies bits 6-10 and rA occupies bits 11-15.
    result = 0
    for (i = 0; i < 5; i++) {
        bit = int(word / (2 ^ (31 - first_bit - i))) % 2
        result = result * 2 + bit
    }
    return result
}
function fail(offset, type,    message) {
    message = "Unsupported relocation " type " at object offset " offset
    if (offset in words) {
        message = message " (instruction 0x" words[offset] ")"
    }
    print message > "/dev/stderr"
    exit 1
}
function emit(offset,    word, opcode, rd, ra) {
    if (!(offset in reloc_type)) {
        print ".long 0x" words[offset] > output
        return
    }

    if (reloc_type[offset] == "R_PPC_REL24") {
        print "bl " reloc_symbol[offset] > output
        return
    }

    word = hex_value(words[offset])
    opcode = int(word / 67108864)
    rd = reg(word, 6)
    ra = reg(word, 11)

    if (reloc_type[offset] == "R_PPC_ADDR16_HA") {
        if (opcode != 15) {
            fail(offset, reloc_type[offset])
        }
        if (ra == 0) {
            print "lis r" rd ", " reloc_symbol[offset] "@ha" > output
        } else {
            print "addis r" rd ", r" ra ", " reloc_symbol[offset] "@ha" > output
        }
        return
    }

    if (reloc_type[offset] == "R_PPC_ADDR16_LO") {
        # D-form load/store opcodes; bit 0 of the word distinguishes the
        # integer width for the halfword and floating-point pairs.
        mnemonics[14] = "addi"
        mnemonics[32] = "lwz"
        mnemonics[33] = "lwzu"
        mnemonics[34] = "lbz"
        mnemonics[35] = "lbzu"
        mnemonics[36] = "stw"
        mnemonics[37] = "stwu"
        mnemonics[38] = "stb"
        mnemonics[39] = "stbu"
        mnemonics[40] = (word % 2 == 0 ? "lhz" : "lhau")
        mnemonics[41] = "lhzu"
        mnemonics[42] = (word % 2 == 0 ? "lha" : "lhax")
        mnemonics[43] = "lhaux"
        mnemonics[44] = (word % 2 == 0 ? "sth" : "sthe")
        mnemonics[45] = "sthu"
        mnemonics[48] = "lfs"
        mnemonics[49] = "lfsu"
        mnemonics[50] = "lfd"
        mnemonics[51] = "lfdu"
        mnemonics[52] = "stfs"
        mnemonics[53] = "stfsu"
        mnemonics[54] = "stfd"
        mnemonics[55] = "stfdu"

        if (opcode == 14) {
            if (ra == 0) {
                print "li r" rd ", " reloc_symbol[offset] "@l" > output
            } else {
                print "addi r" rd ", r" ra ", " reloc_symbol[offset] "@l" > output
            }
            return
        }

        if (opcode in mnemonics) {
            name = mnemonics[opcode]
            # addi is integer; 40 and up use the floating-point register file
            if (opcode >= 40) {
                operand = "f"
            } else {
                operand = "r"
            }
            print name " " operand rd ", " reloc_symbol[offset] "@l(r" ra ")" > output
            return
        }

        fail(offset, reloc_type[offset])
    }

    fail(offset, reloc_type[offset])
}
/^Disassembly of section \.text:/ {
    in_text = 1
    next
}
in_text && /^Disassembly of section / {
    in_text = 0
}
in_text && /^[[:space:]]*[[:xdigit:]]+:[[:space:]]+[[:xdigit:]][[:xdigit:]][[:space:]]/ {
    offset_text = $1
    sub(/:$/, "", offset_text)
    offset = hex_value(offset_text)
    if (offset < 0 || $2 !~ /^[[:xdigit:]][[:xdigit:]]$/ ||
        $3 !~ /^[[:xdigit:]][[:xdigit:]]$/ ||
        $4 !~ /^[[:xdigit:]][[:xdigit:]]$/ ||
        $5 !~ /^[[:xdigit:]][[:xdigit:]]$/) {
        invalid = 1
        next
    }
    words[offset] = tolower($2 $3 $4 $5)
    if (offset > max_offset) {
        max_offset = offset
    }
    instruction_count++
    next
}
in_text && /^[[:space:]]*[[:xdigit:]]+:[[:space:]]+R_PPC_/ {
    offset_text = $1
    sub(/:$/, "", offset_text)
    # objdump reports the byte offset of the patched field, which is inside the
    # instruction word; index relocations by the word they belong to.
    offset = hex_value(offset_text)
    offset = int(offset / 4) * 4
    reloc_type[offset] = $2
    reloc_symbol[offset] = $3
}
END {
    if (invalid || instruction_count == 0) {
        print "Unsupported instruction encoding in object file" > "/dev/stderr"
        exit 1
    }
    for (offset = 0; offset <= max_offset; offset += 4) {
        if (!(offset in words)) {
            print "Unexpected gap in function at object offset " offset > "/dev/stderr"
            exit 1
        }
        emit(offset)
    }
    close(output)
}
'
