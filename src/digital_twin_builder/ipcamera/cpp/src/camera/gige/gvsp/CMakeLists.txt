add_library(gvsp ${CMAKE_CURRENT_SOURCE_DIR}/client.cpp ${CMAKE_CURRENT_SOURCE_DIR}/payload.cpp)

target_link_libraries(gvsp PUBLIC Boost::boost Boost::system utils)

target_include_directories(gvsp PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
