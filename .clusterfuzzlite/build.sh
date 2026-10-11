#!/bin/bash -eu

# Install querylens package and dependencies into Python environment,
# ignoring Requires-Python constraint since base-builder-python runs Python 3.11
pip3 install --ignore-requires-python .

# Compile python fuzz targets into $OUT
for fuzzer in $(find .clusterfuzzlite -maxdepth 1 -name 'fuzz_*.py'); do
    compile_python_fuzzer "$fuzzer"
done

# Copy seed corpora into $OUT
for corpus in .clusterfuzzlite/*_seed_corpus.zip; do
    if [ -f "$corpus" ]; then
        cp "$corpus" "$OUT/"
    fi
done
