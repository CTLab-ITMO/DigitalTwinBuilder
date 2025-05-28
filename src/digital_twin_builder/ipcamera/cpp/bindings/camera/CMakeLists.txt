cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: camera bindings")

set(TARGET_OUTPUT_DIR ${CMAKE_SOURCE_DIR}/python/ipcamera/camera)
pybind11_add_module(_camera bindings.cpp)

add_subdirectory(gige)
add_subdirectory(rtsp)

target_link_libraries(_camera PRIVATE camera pybind11::module)

set_target_properties(_camera PROPERTIES 
    LIBRARY_OUTPUT_DIRECTORY ${TARGET_OUTPUT_DIR}
    SUFFIX ".so"
)
