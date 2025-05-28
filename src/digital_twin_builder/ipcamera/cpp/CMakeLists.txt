cmake_minimum_required(VERSION 3.28)

project(digital_twin)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON CACHE INTERNAL "")
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++20 -O3")
set(GCC_COVERAGE_COMPILE_FLAGS "-fPIC")
set(CMAKE_CXX_FLAGS  "${CMAKE_CXX_FLAGS} ${GCC_COVERAGE_COMPILE_FLAGS}")

set(CMAKE_INSTALL_PREFIX ${PROJECT_SOURCE_DIR})
set(Boost_USE_STATIC_LIBS   ON)

find_package(Boost CONFIG REQUIRED COMPONENTS system)
find_package(libzip CONFIG REQUIRED)
find_package(pugixml CONFIG REQUIRED)
find_package(Python3 COMPONENTS Development REQUIRED)

include(FetchContent)
FetchContent_Declare(
  pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11.git
  GIT_TAG v2.11.1  # Specific version
)
FetchContent_MakeAvailable(pybind11)

include_directories(${CMAKE_SOURCE_DIR}/src)

# add_executable(tests)
add_executable(main)

# add_subdirectory(test)
add_subdirectory(src)
add_subdirectory(bindings)

target_include_directories(main PUBLIC ${Boost_INCLUDE_DIRS})
# target_include_directories(tests PUBLIC ${Boost_INCLUDE_DIRS})

target_link_libraries(main Boost::boost Boost::system camera libzip::zip pugixml::static pugixml::pugixml)
