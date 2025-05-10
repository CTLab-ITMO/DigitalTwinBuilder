cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: gvsp bindings")

set(TARGET_OUTPUT_DIR ${CMAKE_SOURCE_DIR}/python/ipcamera/camera/gige/gvsp)
pybind11_add_module(_gvsp bindings.cpp)

target_link_libraries(_gvsp PRIVATE gvsp pybind11::module)

set_target_properties(_gvsp PROPERTIES 
    LIBRARY_OUTPUT_DIRECTORY ${TARGET_OUTPUT_DIR}
    SUFFIX ".so"
)
