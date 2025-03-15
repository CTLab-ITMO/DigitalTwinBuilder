message(STATUS "CMake: camera")
add_library(camera client.cpp)

add_subdirectory(gige)
add_subdirectory(rtsp)

target_link_libraries(camera PRIVATE gige rtsp)
target_include_directories(camera PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
