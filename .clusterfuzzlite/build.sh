#!/bin/bash -eu

# Install pinned dependencies and build backend with hash verification
pip install --require-hashes -r .clusterfuzzlite/requirements.txt

# Install querylens into Python environment using pre-installed build backend,
# ignoring Requires-Python constraint since base-builder-python runs Python 3.11
pip install --no-build-isolation --no-deps --ignore-requires-python .

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
