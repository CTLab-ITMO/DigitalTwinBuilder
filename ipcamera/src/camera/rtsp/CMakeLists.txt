add_library(rtsp ${CMAKE_CURRENT_SOURCE_DIR}/client.cpp)

target_link_libraries(rtsp PRIVATE Boost::boost Boost::system)

target_include_directories(rtsp PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

