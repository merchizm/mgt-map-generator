cmake_minimum_required(VERSION 3.21.0)

project(mgt_qlementine_style_plugin LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(Qt6 REQUIRED COMPONENTS Core Widgets Svg)
qt_standard_project_setup()

include(FetchContent)
FetchContent_Declare(
  Qlementine
  GIT_REPOSITORY https://github.com/oclero/qlementine.git
  GIT_TAG v1.4.2
)
FetchContent_MakeAvailable(Qlementine)

qt_add_plugin(mgt_qlementine_style_plugin
  CLASS_NAME MgtQlementineStylePlugin
  mgt_qlementine_style_plugin.cpp
  mgt_qlementine_style_plugin.qrc
)

target_link_libraries(mgt_qlementine_style_plugin
  PRIVATE
    Qt6::Core
    Qt6::Widgets
    qlementine
)

set_target_properties(mgt_qlementine_style_plugin
  PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/styles"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/styles"
)
