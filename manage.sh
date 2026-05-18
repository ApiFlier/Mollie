#!/bin/bash
# This script has been renamed to menu.sh.
# Run ./menu.sh for the interactive menu.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/menu.sh" "$@"
