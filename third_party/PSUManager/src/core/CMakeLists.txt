add_library(psu-core STATIC
    PsuArchive.cpp
    PsuDate.cpp
)

target_include_directories(psu-core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(psu-core PUBLIC cxx_std_17)

if(BUILD_TESTING)
    add_executable(psu-core-tests tests/PsuArchiveTests.cpp)
    target_link_libraries(psu-core-tests PRIVATE psu-core)
    add_test(NAME psu-core-tests COMMAND psu-core-tests)
endif()
