cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(rf_sense_node)

# O mesmo app estático usado pelo FastAPI e pelo Netlify é gravado na placa.
spiffs_create_partition_image(
  storage
  ${CMAKE_CURRENT_LIST_DIR}/../../src/rf_sense/static
  FLASH_IN_PROJECT
)

