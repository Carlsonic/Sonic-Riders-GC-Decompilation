#!/bin/sh
set -eu

source_file=$1
body_file=$2
start_label=$3
# End marker: either a label name (lbl_001BC640) or an assembly comment address (001BC640).
end_marker=$4
output_file=$5
temporary_file="${output_file}.tmp"

mkdir -p "$(dirname "$output_file")"

awk -v body="$body_file" -v output="$temporary_file" \
    -v start="$start_label" -v end="$end_marker" '
BEGIN {
    while ((getline line < body) > 0) {
        replacement = replacement line "\n"
    }
    close(body)
    printf "" > output
    close(output)
}
$0 == start ":" {
    state = 1
    print > output
    next
}
state == 1 && $0 ~ /^\.[a-zA-Z]/ {
    # Directives between the two labels describe the function that follows, so
    # keep them and re-emit them with the end label. Dropping a .global or .type
    # here silently changes how the linker resolves the symbol.
    pending = pending $0 "\n"
    next
}
state == 1 && ($0 == end ":" || index($0, "/* " end " ") == 1) {
    printf "%s", replacement > output
    printf "%s", pending > output
    pending = ""
    print > output
    state = 2
    next
}
state == 0 {
    print > output
    next
}
state == 2 {
    print > output
}
END {
    close(output)
    if (state != 2) {
        print "Unable to replace " start " at the expected function boundaries" > "/dev/stderr"
        exit 1
    }
}
' "$source_file"

mv "$temporary_file" "$output_file"
