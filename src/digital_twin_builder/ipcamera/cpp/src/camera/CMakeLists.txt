cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: camera")
add_library(camera STATIC client.cpp)

add_subdirectory(gige)
add_subdirectory(rtsp)

target_link_libraries(camera PRIVATE gige rtsp)
target_include_directories(camera PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
