cmake_minimum_required(VERSION 3.30)

project(digital_twin)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++23 -O3")

set(CMAKE_INSTALL_PREFIX ${PROJECT_SOURCE_DIR})

find_package(GTest REQUIRED)
find_package(Boost CONFIG REQUIRED COMPONENTS system regex)
include_directories(${Boost_INCLUDE_DIRS})

add_executable(tests)
add_executable(main)

add_subdirectory(test)
add_subdirectory(src)

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  message(STATUS "Enabling libc++...")
  target_compile_options(tests PUBLIC -stdlib=libc++)
  target_link_options(tests PUBLIC -stdlib=libc++)
endif()

if(CMAKE_BUILD_TYPE MATCHES "Debug")
  message(STATUS "Enabling _GLIBCXX_DEBUG...")
  target_compile_options(tests PUBLIC -D_GLIBCXX_DEBUG)
endif()

target_link_libraries(tests GTest::gtest GTest::gtest_main)
target_link_libraries(main PRIVATE Boost::boost Boost::system Boost::regex)
