#!/bin/bash
# This script has moved. Run ./menu.sh for the interactive menu.
# Or call the implementation directly: scripts/commands/backup.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/commands/backup.sh" "$@"
