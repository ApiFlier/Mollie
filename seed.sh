#!/bin/bash
# This script has moved. Run ./menu.sh → [7] Advanced tools for seed operations.
# Or call the implementation directly: scripts/commands/seed.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/commands/seed.sh" "$@"
