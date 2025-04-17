message(STATUS "CMake: utils")

add_library(utils ${CMAKE_CURRENT_SOURCE_DIR}/utils.cpp)

target_include_directories(utils PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

