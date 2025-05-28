cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: gvcp bindings")

set(TARGET_OUTPUT_DIR ${CMAKE_SOURCE_DIR}/python/ipcamera/camera/gige/gvcp)
pybind11_add_module(_gvcp bindings.cpp)

target_link_libraries(_gvcp PRIVATE gvcp pybind11::module)

set_target_properties(_gvcp PROPERTIES 
    LIBRARY_OUTPUT_DIRECTORY ${TARGET_OUTPUT_DIR}
    SUFFIX ".so"
)
