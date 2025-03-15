
add_library(gvcp ${CMAKE_CURRENT_SOURCE_DIR}/command.cpp ${CMAKE_CURRENT_SOURCE_DIR}/ack.cpp ${CMAKE_CURRENT_SOURCE_DIR}/client.cpp)

target_link_libraries(gvcp PRIVATE Boost::boost Boost::system)

target_include_directories(gvcp PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} Boost::boost Boost::asio)

