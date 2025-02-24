#!/bin/bash
set -euo pipefail

mkdir -p build
rm -rf build/*
cmake "-DCMAKE_TOOLCHAIN_FILE=~/vcpkg/scripts/buildsystems/vcpkg.cmake" "-DBOOST_ROOT=/opt/homebrew/Cellar/boost/1_87_0" --preset $1 -S .
cmake --build ./build

