#!/bin/bash
# This script has moved. Run ./menu.sh → [7] Advanced tools → Seed workflow.
# Or call the implementation directly: scripts/commands/publish-seed.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/commands/publish-seed.sh" "$@"
