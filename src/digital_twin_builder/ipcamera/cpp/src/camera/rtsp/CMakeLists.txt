cmake_minimum_required(VERSION 3.28)
add_library(rtsp STATIC client.cpp)

target_link_libraries(rtsp PRIVATE Boost::boost Boost::system)

target_include_directories(rtsp PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

