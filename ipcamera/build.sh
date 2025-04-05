#!/bin/bash
set -euo pipefail

mkdir -p build
rm -rf build/*
cmake "-DBOOST_ROOT=~/.local/opt/boost/" "-DCMAKE_TOOLCHAIN_FILE=~/vcpkg/scripts/buildsystems/vcpkg.cmake" --preset $1 -S .
cmake --build ./build

