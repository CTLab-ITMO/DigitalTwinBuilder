message(STATUS "CMake: src")

target_sources(main PRIVATE main.cpp)

add_subdirectory(camera)
