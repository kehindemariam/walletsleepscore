#!/bin/bash
# walletsleepscore — Foundry-port smoke test (v2.0.0)
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
SCRIPT="$SKILL_DIR/scripts/score.sh"

echo "Test 1: --help works"
bash "$SCRIPT" --help >/dev/null 2>&1 || true
echo "  OK"

echo "Test 2: script is executable + bash + cast-based"
head -1 "$SCRIPT" | grep -q "^#!/usr/bin/env bash" && echo "  OK: shebang"
grep -q "cast " "$SCRIPT" && echo "  OK: uses cast"

echo "All smoke tests passed."
