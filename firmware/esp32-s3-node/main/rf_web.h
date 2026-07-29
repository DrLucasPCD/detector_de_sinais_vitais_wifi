#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

esp_err_t rf_web_start(void);
void rf_web_broadcast(const uint8_t *data, size_t len);
uint32_t rf_web_dropped_frames(void);

