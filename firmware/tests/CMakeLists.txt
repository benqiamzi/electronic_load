cmake_minimum_required(VERSION 3.22)

project(electronic_load_tests LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(load_math_test load_math_test.cpp)
target_include_directories(load_math_test PRIVATE ${CMAKE_CURRENT_LIST_DIR}/..)

enable_testing()
add_test(NAME load_math_test COMMAND load_math_test)
