#!/bin/bash

set -e

git switch main
git switch -c comfy-build
git am comfy-patches/*.patch

echo "ComfyWebKit patches applied successfully!"
