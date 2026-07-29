#include <inttypes.h>

#include "esp_log.h"
#include "nvs_flash.h"

#include "rf_web.h"
#include "rf_wifi_csi.h"

static const char *TAG = "rf_main";

static void init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
}

void app_main(void)
{
    init_nvs();
    ESP_LOGI(TAG, "RF Sense firmware 0.1.0; node_id=%d", CONFIG_RF_NODE_ID);
    ESP_LOGI(TAG, "Conectando à rede; a senha nunca é impressa");

    ESP_ERROR_CHECK(rf_wifi_connect());
    ESP_ERROR_CHECK(rf_web_start());
    ESP_ERROR_CHECK(rf_csi_start());

    ESP_LOGI(TAG, "Dashboard: http://%s.local", CONFIG_RF_HOSTNAME);
    ESP_LOGI(TAG, "CSI wire v1 ativo em ws://%s.local/ws/csi", CONFIG_RF_HOSTNAME);
}

