target_sources(main PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/command.cpp ${CMAKE_CURRENT_SOURCE_DIR}/client.cpp )
target_sources(tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/command.cpp)

target_include_directories(main PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_include_directories(tests PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
