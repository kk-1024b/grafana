cmake_minimum_required(VERSION 3.10)
project(fake-project LANGUAGES CXX)
add_executable(fake-test main.cpp)
add_test(NAME fake_test COMMAND fake-test)