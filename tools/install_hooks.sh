#!/bin/sh
# Install the repository's git hooks into .git/hooks. Run once per clone.
set -eu

repo=$(git rev-parse --show-toplevel)
for hook in "$repo"/tools/git-hooks/*; do
    name=$(basename "$hook")
    target="$repo/.git/hooks/$name"
    cp "$hook" "$target"
    chmod +x "$target"
    echo "installed $name"
done