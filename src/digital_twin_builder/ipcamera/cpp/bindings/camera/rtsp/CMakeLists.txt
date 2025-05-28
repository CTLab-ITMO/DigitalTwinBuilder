cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: rtsp bindings")

set(TARGET_OUTPUT_DIR ${CMAKE_SOURCE_DIR}/python/ipcamera/camera/rtsp)
pybind11_add_module(_rtsp bindings.cpp)

target_link_libraries(_rtsp PRIVATE rtsp pybind11::module)

set_target_properties(_rtsp PROPERTIES 
    LIBRARY_OUTPUT_DIRECTORY ${TARGET_OUTPUT_DIR}
    SUFFIX ".so"
)
