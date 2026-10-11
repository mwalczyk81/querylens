#!/bin/bash -eu

# Install querylens package and dependencies into Python environment
pip3 install .

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
