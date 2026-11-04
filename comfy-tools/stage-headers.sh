#!/bin/bash
# Restage consumer-facing macOS headers without building the WebKit library.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: $0 [configured-cmake-build-directory]"
    echo "Default: $ROOT/WebKitBuild/cmake-mac/Release"
    exit 0
fi
if [[ $# -gt 1 ]]; then
    echo "error: expected at most one configured CMake build directory" >&2
    exit 1
fi
BUILD_DIR="${1:-$ROOT/WebKitBuild/cmake-mac/Release}"
if [[ ! -f "$ROOT/Source/WebKit/PlatformMacFrameworkHeaders.cmake" ]]; then
    echo "error: patched header staging is unavailable; run patches.py setup first" >&2
    exit 1
fi
if [[ ! -f "$BUILD_DIR/CMakeCache.txt" ]]; then
    echo "error: no configured CMake build found at $BUILD_DIR" >&2
    exit 1
fi
exec cmake --build "$BUILD_DIR" --target WebKit_StageFrameworkHeaders
