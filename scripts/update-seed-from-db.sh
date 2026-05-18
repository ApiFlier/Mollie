#!/bin/bash
# Compatibility wrapper — the seed refresh tool moved to scripts/commands/.
# Use ./menu.sh → [7] Advanced tools → Seed workflow for the interactive path.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/commands/update-seed.sh" "$@"
