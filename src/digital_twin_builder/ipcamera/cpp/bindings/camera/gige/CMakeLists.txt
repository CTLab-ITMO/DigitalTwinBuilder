cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: gige bindings")

set(TARGET_OUTPUT_DIR ${PYTHON_DIR}/ipcamera/camera/gige)
pybind11_add_module(_gige bindings.cpp)

add_subdirectory(gvcp)
add_subdirectory(gvsp)

target_link_libraries(_gige PRIVATE gige pybind11::module)

set_target_properties(_gige PROPERTIES 
    LIBRARY_OUTPUT_DIRECTORY ${TARGET_OUTPUT_DIR}
    SUFFIX ".so"
)
