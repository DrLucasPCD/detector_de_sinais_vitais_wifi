idf_component_register(
  SRCS
    "main.c"
    "rf_web.c"
    "rf_wifi_csi.c"
  INCLUDE_DIRS "."
  REQUIRES
    esp_event
    esp_http_server
    esp_netif
    esp_timer
    esp_wifi
    lwip
    nvs_flash
    spiffs
    mdns
)
