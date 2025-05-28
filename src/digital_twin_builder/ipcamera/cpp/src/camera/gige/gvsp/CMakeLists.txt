cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: gvsp")

add_library(gvsp STATIC client.cpp payload.cpp traits.cpp)

target_link_libraries(gvsp PUBLIC Boost::boost Boost::system utils)

target_include_directories(gvsp PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
