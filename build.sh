#!/bin/bash
set -euo pipefail
IFS=$' \t\n'

mkdir -p build
rm -rf build/*
cmake "-DCMAKE_TOOLCHAIN_FILE=/Users/gozebone/vcpkg/scripts/buildsystems/vcpkg.cmake" --preset $1 \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=1 -DENABLE_SLOW_TEST=ON -DTREAT_WARNINGS_AS_ERRORS=ON -S .
cmake --build ./build

