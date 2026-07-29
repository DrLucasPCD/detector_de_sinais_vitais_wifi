#pragma once

#include "esp_err.h"

esp_err_t rf_wifi_connect(void);
esp_err_t rf_csi_start(void);
uint32_t rf_csi_queue_drops(void);

