#!/bin/bash
# This script has moved. Run ./menu.sh → [5] Troubleshoot for diagnostics.
# Or call the implementation directly: scripts/commands/troubleshoot.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/commands/troubleshoot.sh" "$@"
