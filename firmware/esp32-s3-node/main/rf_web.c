#include "rf_web.h"

#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "esp_http_server.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_spiffs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
#include "mdns.h"

#include "rf_wifi_csi.h"
#include "rf_wire.h"

#define RF_WS_POOL_SIZE 4
#define RF_HTTP_CHUNK 1024
#define RF_MAX_CLIENTS 6

typedef struct {
    bool in_use;
    size_t len;
    uint8_t data[RF_MAX_WIRE_BYTES];
} ws_work_t;

static const char *TAG = "rf_web";
static httpd_handle_t s_server;
static ws_work_t s_pool[RF_WS_POOL_SIZE];
static portMUX_TYPE s_pool_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t s_dropped_frames;

static const char *content_type(const char *path)
{
    const char *extension = strrchr(path, '.');
    if (extension == NULL) {
        return "application/octet-stream";
    }
    if (strcmp(extension, ".html") == 0) return "text/html; charset=utf-8";
    if (strcmp(extension, ".css") == 0) return "text/css; charset=utf-8";
    if (strcmp(extension, ".js") == 0) return "text/javascript; charset=utf-8";
    if (strcmp(extension, ".json") == 0) return "application/json";
    return "application/octet-stream";
}

static esp_err_t send_file(httpd_req_t *req, const char *path)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        ESP_LOGW(TAG, "Arquivo ausente: %s (%d)", path, errno);
        return ESP_ERR_NOT_FOUND;
    }

    httpd_resp_set_type(req, content_type(path));
    httpd_resp_set_hdr(req, "X-Content-Type-Options", "nosniff");
    httpd_resp_set_hdr(req, "Cache-Control",
                       strstr(path, "index.html") ? "no-cache" : "public, max-age=86400");

    char buffer[RF_HTTP_CHUNK];
    size_t read;
    while ((read = fread(buffer, 1, sizeof(buffer), file)) > 0) {
        if (httpd_resp_send_chunk(req, buffer, read) != ESP_OK) {
            fclose(file);
            httpd_resp_sendstr_chunk(req, NULL);
            return ESP_FAIL;
        }
    }
    fclose(file);
    return httpd_resp_send_chunk(req, NULL, 0);
}

static esp_err_t static_handler(httpd_req_t *req)
{
    const char *uri = req->uri;
    char path[160];
    if (strcmp(uri, "/") == 0) {
        uri = "/index.html";
    }
    if (strstr(uri, "..") != NULL || snprintf(path, sizeof(path), "/spiffs%s", uri) >= sizeof(path)) {
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "caminho inválido");
    }
    struct stat info;
    if (stat(path, &info) != 0) {
        strcpy(path, "/spiffs/index.html");
    }
    if (send_file(req, path) != ESP_OK) {
        return httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "arquivo não encontrado");
    }
    return ESP_OK;
}

static esp_err_t health_handler(httpd_req_t *req)
{
    char response[192];
    int length = snprintf(
        response,
        sizeof(response),
        "{\"status\":\"ok\",\"version\":\"0.1.0\",\"node_id\":%d,"
        "\"queue_drops\":%" PRIu32 ",\"ws_drops\":%" PRIu32 "}",
        CONFIG_RF_NODE_ID,
        rf_csi_queue_drops(),
        rf_web_dropped_frames());
    httpd_resp_set_type(req, HTTPD_TYPE_JSON);
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, response, length);
}

static esp_err_t ws_handler(httpd_req_t *req)
{
    if (req->method == HTTP_GET) {
        ESP_LOGI(TAG, "Cliente WebSocket conectado, fd=%d", httpd_req_to_sockfd(req));
        return ESP_OK;
    }

    httpd_ws_frame_t frame = {0};
    frame.type = HTTPD_WS_TYPE_BINARY;
    esp_err_t err = httpd_ws_recv_frame(req, &frame, 0);
    if (err != ESP_OK || frame.len == 0) {
        return err;
    }
    uint8_t scratch[32];
    if (frame.len > sizeof(scratch)) {
        return ESP_ERR_INVALID_SIZE;
    }
    frame.payload = scratch;
    return httpd_ws_recv_frame(req, &frame, sizeof(scratch));
}

static void ws_send_work(void *argument)
{
    ws_work_t *work = argument;
    int clients[RF_MAX_CLIENTS];
    size_t client_count = RF_MAX_CLIENTS;
    if (s_server != NULL && httpd_get_client_list(s_server, &client_count, clients) == ESP_OK) {
        httpd_ws_frame_t frame = {
            .final = true,
            .fragmented = false,
            .type = HTTPD_WS_TYPE_BINARY,
            .payload = work->data,
            .len = work->len,
        };
        for (size_t index = 0; index < client_count; ++index) {
            int fd = clients[index];
            if (httpd_ws_get_fd_info(s_server, fd) == HTTPD_WS_CLIENT_WEBSOCKET) {
                if (httpd_ws_send_frame_async(s_server, fd, &frame) != ESP_OK) {
                    httpd_sess_trigger_close(s_server, fd);
                }
            }
        }
    }

    portENTER_CRITICAL(&s_pool_lock);
    work->in_use = false;
    portEXIT_CRITICAL(&s_pool_lock);
}

void rf_web_broadcast(const uint8_t *data, size_t len)
{
    if (s_server == NULL || data == NULL || len == 0 || len > RF_MAX_WIRE_BYTES) {
        return;
    }
    ws_work_t *selected = NULL;
    portENTER_CRITICAL(&s_pool_lock);
    for (size_t index = 0; index < RF_WS_POOL_SIZE; ++index) {
        if (!s_pool[index].in_use) {
            s_pool[index].in_use = true;
            selected = &s_pool[index];
            break;
        }
    }
    portEXIT_CRITICAL(&s_pool_lock);

    if (selected == NULL) {
        s_dropped_frames++;
        return;
    }
    memcpy(selected->data, data, len);
    selected->len = len;
    if (httpd_queue_work(s_server, ws_send_work, selected) != ESP_OK) {
        portENTER_CRITICAL(&s_pool_lock);
        selected->in_use = false;
        portEXIT_CRITICAL(&s_pool_lock);
        s_dropped_frames++;
    }
}

uint32_t rf_web_dropped_frames(void)
{
    return s_dropped_frames;
}

esp_err_t rf_web_start(void)
{
    esp_vfs_spiffs_conf_t spiffs = {
        .base_path = "/spiffs",
        .partition_label = "storage",
        .max_files = 8,
        .format_if_mount_failed = false,
    };
    ESP_RETURN_ON_ERROR(esp_vfs_spiffs_register(&spiffs), TAG, "falha ao montar UI");

    ESP_RETURN_ON_ERROR(mdns_init(), TAG, "falha no mDNS");
    ESP_RETURN_ON_ERROR(mdns_hostname_set(CONFIG_RF_HOSTNAME), TAG, "falha no hostname");
    ESP_RETURN_ON_ERROR(mdns_instance_name_set("RF Sense ESP32-S3"), TAG, "falha no nome mDNS");
    ESP_RETURN_ON_ERROR(
        mdns_service_add("RF Sense", "_http", "_tcp", 80, NULL, 0),
        TAG,
        "falha ao anunciar HTTP");

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_open_sockets = RF_MAX_CLIENTS;
    config.max_uri_handlers = 8;
    config.lru_purge_enable = true;
    config.uri_match_fn = httpd_uri_match_wildcard;
    ESP_RETURN_ON_ERROR(httpd_start(&s_server, &config), TAG, "falha ao iniciar HTTP");

    httpd_uri_t websocket = {
        .uri = "/ws/csi",
        .method = HTTP_GET,
        .handler = ws_handler,
        .is_websocket = true,
        .handle_ws_control_frames = true,
    };
    httpd_uri_t health = {
        .uri = "/health",
        .method = HTTP_GET,
        .handler = health_handler,
    };
    httpd_uri_t files = {
        .uri = "/*",
        .method = HTTP_GET,
        .handler = static_handler,
    };
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(s_server, &websocket), TAG, "ws");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(s_server, &health), TAG, "health");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(s_server, &files), TAG, "files");
    return ESP_OK;
}
