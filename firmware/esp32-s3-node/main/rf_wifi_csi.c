#include "rf_wifi_csi.h"

#include <inttypes.h>
#include <string.h>

#include "esp_event.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"

#include "rf_web.h"
#include "rf_wire.h"

#define WIFI_CONNECTED_BIT BIT0
#define CSI_QUEUE_LENGTH 8

typedef struct {
    uint16_t len;
    uint32_t frequency_mhz;
    int8_t rssi_dbm;
    int8_t noise_floor_dbm;
    uint16_t flags;
    int8_t iq[RF_MAX_SUBCARRIERS * 2];
} csi_packet_t;

static const char *TAG = "rf_csi";
static EventGroupHandle_t s_wifi_events;
static QueueHandle_t s_csi_queue;
static uint32_t s_sequence;
static uint32_t s_queue_drops;
static uint32_t s_source_drops;
static uint32_t s_layout_drops;
static int64_t s_last_csi_us;
static uint8_t s_ap_bssid[6];
static size_t s_expected_csi_bytes;

static uint32_t channel_frequency(uint8_t channel)
{
    if (channel == 14) return 2484;
    if (channel >= 1 && channel <= 13) return 2412 + (channel - 1) * 5;
    return 0;
}

static void wifi_event(
    void *argument,
    esp_event_base_t base,
    int32_t event_id,
    void *event_data)
{
    (void)argument;
    (void)event_data;
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
        ESP_LOGW(TAG, "Wi-Fi desconectado; tentando novamente");
        esp_wifi_connect();
    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = event_data;
        ESP_LOGI(TAG, "IP obtido: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

esp_err_t rf_wifi_connect(void)
{
    if (strlen(CONFIG_RF_WIFI_SSID) == 0) {
        ESP_LOGE(TAG, "Configure RF_WIFI_SSID em idf.py menuconfig");
        return ESP_ERR_INVALID_STATE;
    }
    s_wifi_events = xEventGroupCreate();
    if (s_wifi_events == NULL) {
        return ESP_ERR_NO_MEM;
    }

    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "esp_netif");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event loop");
    esp_netif_t *station = esp_netif_create_default_wifi_sta();
    if (station == NULL) {
        return ESP_ERR_NO_MEM;
    }
    ESP_RETURN_ON_ERROR(
        esp_netif_set_hostname(station, CONFIG_RF_HOSTNAME),
        TAG,
        "hostname");

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init), TAG, "wifi init");
    ESP_RETURN_ON_ERROR(
        esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL),
        TAG,
        "wifi handler");
    ESP_RETURN_ON_ERROR(
        esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL),
        TAG,
        "ip handler");

    wifi_config_t config = {0};
    strlcpy((char *)config.sta.ssid, CONFIG_RF_WIFI_SSID, sizeof(config.sta.ssid));
    strlcpy(
        (char *)config.sta.password,
        CONFIG_RF_WIFI_PASSWORD,
        sizeof(config.sta.password));
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    config.sta.pmf_cfg.capable = true;
    config.sta.pmf_cfg.required = false;

    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "wifi mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &config), TAG, "wifi config");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "wifi start");
    ESP_RETURN_ON_ERROR(esp_wifi_set_ps(WIFI_PS_NONE), TAG, "wifi power save");

    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_events,
        WIFI_CONNECTED_BIT,
        pdFALSE,
        pdTRUE,
        pdMS_TO_TICKS(30000));
    return (bits & WIFI_CONNECTED_BIT) ? ESP_OK : ESP_ERR_TIMEOUT;
}

static void csi_callback(void *context, wifi_csi_info_t *info)
{
    (void)context;
    if (info == NULL || info->buf == NULL || info->len < 2) {
        return;
    }
    if (memcmp(info->mac, s_ap_bssid, sizeof(s_ap_bssid)) != 0) {
        s_source_drops++;
        return;
    }
    const int64_t now = esp_timer_get_time();
    const int64_t minimum_interval = 1000000LL / CONFIG_RF_STREAM_FPS;
    if (now - s_last_csi_us < minimum_interval) {
        return;
    }
    s_last_csi_us = now;

    /*
     * O ESP32-S3 pode marcar a primeira palavra como inválida. Removemos
     * sempre os dois primeiros pares I/Q para manter o mesmo layout entre
     * quadros, independentemente da flag.
     */
    size_t offset = info->len > 4 ? 4 : 0;
    size_t available = info->len - offset;
    available -= available % 2;
    if (available > sizeof(((csi_packet_t *)0)->iq)) {
        available = sizeof(((csi_packet_t *)0)->iq);
    }
    if (s_expected_csi_bytes == 0) {
        s_expected_csi_bytes = available;
    } else if (available != s_expected_csi_bytes) {
        s_layout_drops++;
        return;
    }
    csi_packet_t packet = {
        .len = available,
        .frequency_mhz = channel_frequency(info->rx_ctrl.channel),
        .rssi_dbm = info->rx_ctrl.rssi,
        .noise_floor_dbm = info->rx_ctrl.noise_floor,
        .flags = info->first_word_invalid ? 1u : 0u,
    };
    memcpy(packet.iq, info->buf + offset, available);
    if (xQueueSend(s_csi_queue, &packet, 0) != pdTRUE) {
        s_queue_drops++;
    }
}

static int open_udp_socket(struct sockaddr_in *destination)
{
#if CONFIG_RF_UDP_ENABLED
    memset(destination, 0, sizeof(*destination));
    destination->sin_family = AF_INET;
    destination->sin_port = htons(CONFIG_RF_UDP_TARGET_PORT);
    if (inet_pton(AF_INET, CONFIG_RF_UDP_TARGET_IP, &destination->sin_addr) != 1) {
        ESP_LOGE(TAG, "RF_UDP_TARGET_IP inválido");
        return -1;
    }
    return socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
#else
    (void)destination;
    return -1;
#endif
}

static void sender_task(void *argument)
{
    (void)argument;
    uint8_t wire[RF_MAX_WIRE_BYTES];
    struct sockaddr_in destination;
    int udp = open_udp_socket(&destination);
    for (;;) {
        csi_packet_t packet;
        if (xQueueReceive(s_csi_queue, &packet, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        rf_wire_header_t header = {
            .magic = RF_RAW_CSI_MAGIC,
            .node_id = CONFIG_RF_NODE_ID,
            .n_antennas = 1,
            .n_subcarriers = packet.len / 2,
            .frequency_mhz = packet.frequency_mhz,
            .sequence = s_sequence++,
            .rssi_dbm = packet.rssi_dbm,
            .noise_floor_dbm = packet.noise_floor_dbm,
            .flags = packet.flags,
        };
        memcpy(wire, &header, sizeof(header));
        memcpy(wire + sizeof(header), packet.iq, packet.len);
        size_t wire_len = sizeof(header) + packet.len;
        rf_web_broadcast(wire, wire_len);
#if CONFIG_RF_UDP_ENABLED
        if (udp >= 0) {
            sendto(
                udp,
                wire,
                wire_len,
                0,
                (const struct sockaddr *)&destination,
                sizeof(destination));
        }
#endif
    }
}

esp_err_t rf_csi_start(void)
{
    wifi_ap_record_t access_point = {0};
    ESP_RETURN_ON_ERROR(
        esp_wifi_sta_get_ap_info(&access_point),
        TAG,
        "não foi possível obter BSSID do AP");
    memcpy(s_ap_bssid, access_point.bssid, sizeof(s_ap_bssid));
    ESP_LOGI(
        TAG,
        "CSI filtrado no AP %02x:%02x:%02x:%02x:%02x:%02x",
        s_ap_bssid[0],
        s_ap_bssid[1],
        s_ap_bssid[2],
        s_ap_bssid[3],
        s_ap_bssid[4],
        s_ap_bssid[5]);

    s_csi_queue = xQueueCreate(CSI_QUEUE_LENGTH, sizeof(csi_packet_t));
    if (s_csi_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }
    if (xTaskCreatePinnedToCore(
            sender_task,
            "rf_sender",
            6144,
            NULL,
            8,
            NULL,
            1) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    wifi_csi_config_t config = {
        .lltf_en = true,
        .htltf_en = false,
        .stbc_htltf2_en = false,
        .ltf_merge_en = false,
        .channel_filter_en = false,
        .manu_scale = false,
        .shift = 0,
        .dump_ack_en = false,
    };
    ESP_RETURN_ON_ERROR(esp_wifi_set_csi_config(&config), TAG, "csi config");
    ESP_RETURN_ON_ERROR(esp_wifi_set_csi_rx_cb(csi_callback, NULL), TAG, "csi callback");
    ESP_RETURN_ON_ERROR(esp_wifi_set_promiscuous(true), TAG, "promiscuous");
    ESP_RETURN_ON_ERROR(esp_wifi_set_csi(true), TAG, "csi enable");
    ESP_LOGI(TAG, "CSI ativo a no máximo %d fps", CONFIG_RF_STREAM_FPS);
    return ESP_OK;
}

uint32_t rf_csi_queue_drops(void)
{
    return s_queue_drops + s_source_drops + s_layout_drops;
}
