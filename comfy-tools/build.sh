#!/bin/bash
# Build the macOS CMake Release configuration with five parallel jobs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# Match ComfyPortal's minimum supported macOS version, including on newer hosts.
# Pass an additional --cmakeargs option to override this for another build.
exec Tools/Scripts/build-webkit --release --cmake --makeargs="-j5" \
    --cmakeargs="-DCMAKE_OSX_DEPLOYMENT_TARGET=15.4" "$@"
