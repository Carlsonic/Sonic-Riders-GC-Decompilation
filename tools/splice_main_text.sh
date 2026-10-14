#!/bin/sh
# Splice converted C bodies into the monolithic _Main assembly, in order.
#
# Usage: splice_main_text.sh <source asm> <output asm> <start:end:src> ...
#
# One awk pass rewrites every converted function. The previous version ran a full
# pass per function, which on an 18 MB / 490k-line listing meant ~31 passes and
# ~1m40s of pure I/O for a change that only touches a few dozen lines. The output
# is byte-identical; tools/replace_main_text.sh still exists for splicing a
# single body by hand.
set -eu

source_file=$1
output_file=$2
shift 2

manifest="${output_file}.manifest"
trap 'rm -f "$manifest" "${output_file}.tmp"' EXIT

: > "$manifest"
for entry in "$@"; do
    start=$(printf '%s' "$entry" | cut -d: -f1)
    end=$(printf '%s' "$entry" | cut -d: -f2)
    src=$(printf '%s' "$entry" | cut -d: -f3)
    body=".build/main_text/$(basename "$src").inc"

    if [ ! -f "$body" ]; then
        echo "Missing generated body $body for $start" >&2
        exit 1
    fi

    printf '%s\t%s\t%s\n' "$start" "$end" "$body" >> "$manifest"
done

mkdir -p "$(dirname "$output_file")"

awk -v manifest="$manifest" -v output="${output_file}.tmp" '
BEGIN {
    count = 0
    infunc = 0
    while ((getline spec < manifest) > 0) {
        split(spec, parts, "\t")
        start[count] = parts[1]
        end[count] = parts[2]
        body = ""
        while ((getline line < parts[3]) > 0) {
            body = body line "\n"
        }
        close(parts[3])
        replacement[count] = body
        count++
    }
    close(manifest)
    printf "" > output
}
{
    if (!infunc) {
        for (i = 0; i < count; i++) {
            if ($0 == start[i] ":") {
                print > output
                infunc = 1
                active = i
                pending = ""
                break
            }
        }
        if (!infunc) print > output
        next
    }
    # Directives between the two labels describe the function that follows, so
    # keep them and re-emit them with the end label. Dropping a .global or .type
    # here silently changes how the linker resolves the symbol.
    if ($0 ~ /^\.[a-zA-Z]/) { pending = pending $0 "\n"; next }
    if ($0 == end[active] ":" || index($0, "/* " end[active] " ") == 1) {
        printf "%s", replacement[active] > output
        printf "%s", pending > output
        pending = ""
        infunc = 0
        print > output
        # Consecutive converted functions share a label: the end marker of one is
        # the start marker of the next. That line was already emitted above, so
        # open the next body here instead of waiting for a second pass over it.
        for (i = 0; i < count; i++) {
            if ($0 == start[i] ":") { infunc = 1; active = i; pending = ""; break }
        }
        next
    }
}
END {
    if (infunc) {
        print "Unable to find the end marker for " start[active] > "/dev/stderr"
        exit 1
    }
    close(output)
}
' "$source_file"

mv "${output_file}.tmp" "$output_file"
