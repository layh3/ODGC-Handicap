#!/bin/bash
# Run the Python port against RoundData.dat and diff against the golden C++ outputs.
set -e
cd "$(dirname "$0")"
rm -rf py_out && mkdir py_out
cp RoundData.dat py_out/
(cd py_out && python3 ../hc24.py)
echo "--- diff vs golden/ ---"
fail=0
for f in alphHC.txt atosHC.txt evHC.txt kvHC.txt ladiesHC.txt odgcHC.txt odgccaCH.txt rankHC.txt player_rounds.txt; do
  if diff -q "py_out/$f" "golden/$f" >/dev/null 2>&1; then
    echo "  PASS  $f"
  else
    echo "  FAIL  $f"
    fail=1
  fi
done
exit $fail
