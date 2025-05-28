cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: src")

target_sources(main PRIVATE main.cpp)

add_subdirectory(utils)
add_subdirectory(camera)
