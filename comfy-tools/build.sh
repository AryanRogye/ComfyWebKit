#!/bin/bash
# Build the macOS CMake Release configuration with five parallel jobs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec Tools/Scripts/build-webkit --release --cmake --makeargs="-j5" "$@"
