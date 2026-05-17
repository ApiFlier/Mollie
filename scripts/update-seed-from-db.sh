#!/bin/bash
# Compatibility wrapper — the seed refresh tool moved to the repo root.
# Use ./update-seed.sh directly.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/update-seed.sh" "$@"
