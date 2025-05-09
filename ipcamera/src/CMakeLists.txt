message(STATUS "CMake: src")

target_sources(main PRIVATE main.cpp)

add_subdirectory(utils)
add_subdirectory(camera)
