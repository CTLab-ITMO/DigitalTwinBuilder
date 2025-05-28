cmake_minimum_required(VERSION 3.28)
message(STATUS "CMake: gvcp")

add_library(gvcp STATIC command.cpp ack.cpp client.cpp)

target_link_libraries(gvcp PRIVATE Boost::boost Boost::system libzip::zip pugixml::static pugixml::pugixml)

target_include_directories(gvcp PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

