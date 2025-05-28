cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: gige")

add_library(gige STATIC client.cpp)

add_subdirectory(gvcp)
add_subdirectory(gvsp)

target_link_libraries(gige PRIVATE gvcp gvsp)

target_include_directories(gige PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

