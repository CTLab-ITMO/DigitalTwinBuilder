cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: utils")

add_library(utils STATIC utils.cpp)

target_include_directories(utils PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

