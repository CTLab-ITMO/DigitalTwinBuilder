add_library(gvsp ${CMAKE_CURRENT_SOURCE_DIR}/client.cpp)

target_link_libraries(gvsp PUBLIC Boost::boost Boost::system)

target_include_directories(gvsp PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
