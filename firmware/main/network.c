#include "network.h"
#include "audio_io.h"
#include "private_config.h"
#include <stdatomic.h>
#include <string.h>
#include <stdio.h>
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include "cJSON.h"
#include "lwip/sockets.h"
#include "lwip/inet.h"

#define IP_READY BIT0
typedef struct {
    int kind; // 1=connected, 2=disconnected, 3=text, 4=binary
    int len;
    char data[2048];
} net_message_t;
static EventGroupHandle_t wifi_events;
static QueueHandle_t incoming;
static atomic_bool fault;
static esp_websocket_client_handle_t client;
static atomic_bool connected;
static bool capturing, playing;
static char session_id[40];
static uint32_t turn;

bool network_busy(void) { return atomic_load(&connected); }

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) esp_wifi_connect();
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(wifi_events, IP_READY);
        atomic_store(&fault, true);
        esp_wifi_connect();
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(wifi_events, IP_READY);
        ESP_LOGI("wifi", "Station has IP; waiting for PC discovery");
    }
}

static void websocket_event(void *arg, esp_event_base_t base, int32_t id, void *event)
{
    static net_message_t message;
    static int assembly_kind, assembled;
    esp_websocket_event_data_t *data = event;
    if (id == WEBSOCKET_EVENT_CONNECTED || id == WEBSOCKET_EVENT_DISCONNECTED || id == WEBSOCKET_EVENT_CLOSED) {
        message.kind = id == WEBSOCKET_EVENT_CONNECTED ? 1 : 2;
        message.len = 0;
        if (xQueueSend(incoming, &message, 0) != pdTRUE) atomic_store(&fault, true);
    } else if (id == WEBSOCKET_EVENT_DATA && (data->op_code == 1 || data->op_code == 2 || data->op_code == 0)) {
        if (data->payload_offset == 0) {
            assembly_kind = data->op_code == 1 ? 3 : 4;
            assembled = 0;
        }
        // Our protocol sends bounded, unfragmented WS messages; library delivery may split a message.
        if (!data->fin || data->payload_len > sizeof(message.data) - 1 ||
            data->payload_offset != assembled || data->data_len < 0 ||
            assembled + data->data_len > sizeof(message.data) - 1) {
            atomic_store(&fault, true);
            return;
        }
        memcpy(message.data + assembled, data->data_ptr, data->data_len);
        assembled += data->data_len;
        if (assembled == data->payload_len) {
            message.kind = assembly_kind;
            message.len = assembled;
            message.data[assembled] = 0;
            if (xQueueSend(incoming, &message, 0) != pdTRUE) atomic_store(&fault, true);
        }
    }
}

static bool send_text(const char *text)
{
    int n = strlen(text);
    return esp_websocket_client_send_text(client, text, n, pdMS_TO_TICKS(200)) == n;
}

static const char *string_field(cJSON *obj, const char *key)
{
    cJSON *value = cJSON_GetObjectItemCaseSensitive(obj, key);
    return cJSON_IsString(value) ? value->valuestring : "";
}

static void control(const char *text)
{
    cJSON *obj = cJSON_Parse(text);
    if (!obj) { atomic_store(&fault, true); return; }
    const char *kind = string_field(obj, "type");
    const char *sid = string_field(obj, "session_id");
    cJSON *tid = cJSON_GetObjectItemCaseSensitive(obj, "turn_id");
    if (!strcmp(kind, "hello")) {
        if (strlen(sid) != 32) atomic_store(&fault, true);
        else snprintf(session_id, sizeof(session_id), "%s", sid);
    } else if (strcmp(sid, session_id) || !cJSON_IsNumber(tid)) {
        atomic_store(&fault, true);
    } else if (!strcmp(kind, "capture_start")) {
        if (tid->valuedouble <= turn || tid->valuedouble > UINT32_MAX) atomic_store(&fault, true);
        else {
            turn = (uint32_t)tid->valuedouble;
            capturing = true;
            playing = false;
            audio_capture_set(true, turn);
            ESP_LOGI("network", "Capture turn %lu", (unsigned long)turn);
        }
    } else if ((uint32_t)tid->valuedouble != turn) {
        atomic_store(&fault, true);
    } else if (!strcmp(kind, "capture_end")) {
        capturing = false;
        audio_capture_set(false, turn);
    } else if (!strcmp(kind, "play_start")) {
        cJSON *rate = cJSON_GetObjectItemCaseSensitive(obj, "sample_rate");
        if (!cJSON_IsNumber(rate) || rate->valueint != 48000 || strcmp(string_field(obj,"format"),"pcm_s16le")) {
            atomic_store(&fault, true);
        } else {
            audio_play_start();
            capturing = false;
            playing = true;
        }
    } else if (!strcmp(kind, "play_end")) {
        if (!playing) atomic_store(&fault, true);
        else audio_play_end();
    } else if (!strcmp(kind, "stop")) {
        audio_stop();
        capturing = playing = false;
    }
    cJSON_Delete(obj);
}

static bool discover(char *uri, size_t size)
{
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) return false;
    struct sockaddr_in local = {.sin_family=AF_INET, .sin_port=htons(DAFE_DISCOVERY_PORT), .sin_addr.s_addr=htonl(INADDR_ANY)};
    struct timeval timeout = {.tv_sec=2};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    if (bind(sock, (struct sockaddr *)&local, sizeof(local)) < 0) { close(sock); return false; }
    bool found = false;
    while (xEventGroupGetBits(wifi_events) & IP_READY) {
        char buffer[256];
        struct sockaddr_in source;
        socklen_t length = sizeof(source);
        int n = recvfrom(sock, buffer, sizeof(buffer)-1, 0, (struct sockaddr *)&source, &length);
        if (n <= 0) continue;
        buffer[n] = 0;
        cJSON *obj = cJSON_Parse(buffer);
        cJSON *port = obj ? cJSON_GetObjectItemCaseSensitive(obj, "port") : NULL;
        if (obj && !strcmp(string_field(obj,"service"),"dafe-voice") &&
            cJSON_IsNumber(port) && port->valueint == DAFE_SERVER_PORT &&
            !strcmp(string_field(obj,"path"),"/audio")) {
            char ip[INET_ADDRSTRLEN];
            inet_ntoa_r(source.sin_addr, ip, sizeof(ip));
            snprintf(uri, size, "ws://%s:%d/audio", ip, port->valueint);
            found = true;
        }
        cJSON_Delete(obj);
        if (found) break;
    }
    close(sock);
    return found;
}

static void network_task(void *arg)
{
    static net_message_t message;
    static capture_block_t capture;
    while (true) {
        xEventGroupWaitBits(wifi_events, IP_READY, pdFALSE, pdTRUE, portMAX_DELAY);
        char uri[96];
        if (!discover(uri, sizeof(uri))) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
        xQueueReset(incoming);
        audio_stop();
        turn = 0;
        session_id[0] = 0;
        connected = capturing = playing = false;
        atomic_store(&fault, false);
        esp_websocket_client_config_t config = {
            .uri=uri, .disable_auto_reconnect=true, .buffer_size=2048,
            .task_stack=6144, .network_timeout_ms=5000, .ping_interval_sec=10,
        };
        client = esp_websocket_client_init(&config);
        if (!client) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
        ESP_ERROR_CHECK(esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, websocket_event, NULL));
        esp_err_t start = esp_websocket_client_start(client);
        TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(12000);
        while (start == ESP_OK && !atomic_load(&fault) && (xEventGroupGetBits(wifi_events) & IP_READY)) {
            // At the default 100Hz RTOS tick, 5ms rounds down to zero and spins.
            if (xQueueReceive(incoming, &message, pdMS_TO_TICKS(10)) == pdTRUE) {
                if (message.kind == 1) {
                    connected = true;
                    if (!send_text("{\"type\":\"hello\",\"protocol_version\":1,\"capture_rate\":16000,\"playback_rate\":48000,\"format\":\"pcm_s16le\"}")) break;
                } else if (message.kind == 2) break;
                else if (message.kind == 3) control(message.data);
                else if (message.kind == 4 && playing && !audio_play_push(message.data, message.len)) {
                    ESP_LOGW("network", "Playback queue overflow or invalid block; resetting session");
                    break;
                }
            }
            if (!connected && (int32_t)(xTaskGetTickCount()-deadline) >= 0) break;
            if (connected && capturing && xQueueReceive(capture_queue, &capture, 0) == pdTRUE && capture.generation == turn) {
                if (esp_websocket_client_send_bin(client, (char *)capture.samples, sizeof(capture.samples), pdMS_TO_TICKS(200)) != sizeof(capture.samples)) break;
            }
            if (connected && playing && audio_take_played()) {
                char ack[144];
                snprintf(ack, sizeof(ack), "{\"type\":\"played\",\"session_id\":\"%s\",\"turn_id\":%lu}", session_id, (unsigned long)turn);
                playing = false;
                if (!send_text(ack)) break;
            }
        }
        audio_stop();
        esp_websocket_client_stop(client);
        esp_websocket_client_destroy(client);
        client = NULL;
        connected = false;
        ESP_LOGI("network", "Session closed; rediscovering PC");
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void network_start(void)
{
    incoming = xQueueCreate(20, sizeof(net_message_t));
    wifi_events = xEventGroupCreate();
    assert(incoming && wifi_events);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    assert(esp_netif_create_default_wifi_sta());
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t config = {0};
    strlcpy((char *)config.sta.ssid, DAFE_WIFI_SSID, sizeof(config.sta.ssid));
    strlcpy((char *)config.sta.password, DAFE_WIFI_PASSWORD, sizeof(config.sta.password));
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    assert(xTaskCreate(network_task, "network", 8192, NULL, 5, NULL) == pdPASS);
}
