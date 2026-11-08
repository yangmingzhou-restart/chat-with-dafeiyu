#include "audio_io.h"
#include "private_config.h"
#include <stdatomic.h>
#include <string.h>
#include "driver/i2s_std.h"
#include "driver/pulse_cnt.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_rom_gpio.h"
#include "soc/i2s_periph.h"
#include "esp_log.h"
#include "freertos/task.h"

QueueHandle_t capture_queue;
static QueueHandle_t play_queue;
static i2s_chan_handle_t rx, tx;
static atomic_bool capturing, ending, played;
static atomic_bool output_active;
static atomic_uint capture_generation, play_generation;
static uint32_t capture_drops;
static atomic_uint playback_underruns, output_bytes, output_peak;
static pcnt_unit_handle_t wire_counter[3];
static atomic_uint wire_us;
static int64_t wire_started_us;

static void wire_probe_init(void)
{
    const int pins[] = {27, 14, 22};
    const int signals[] = {i2s_periph_signal[1].m_tx_bck_sig,
                           i2s_periph_signal[1].m_tx_ws_sig,
                           i2s_periph_signal[1].data_out_sig};
    for (int i = 0; i < 3; i++) {
        pcnt_unit_config_t unit = {.low_limit = -32768, .high_limit = 32767, .flags.accum_count = true};
        ESP_ERROR_CHECK(pcnt_new_unit(&unit, &wire_counter[i]));
        pcnt_chan_config_t config = {.edge_gpio_num = pins[i], .level_gpio_num = -1, .flags.io_loop_back = true};
        pcnt_channel_handle_t channel;
        // PCNT enables input/output but gpio_config resets the output matrix.
        ESP_ERROR_CHECK(pcnt_new_channel(wire_counter[i], &config, &channel));
        esp_rom_gpio_connect_out_signal(pins[i], signals[i], false, false);
        ESP_ERROR_CHECK(gpio_set_pull_mode(pins[i], GPIO_FLOATING));
        ESP_ERROR_CHECK(pcnt_channel_set_edge_action(channel, PCNT_CHANNEL_EDGE_ACTION_INCREASE, PCNT_CHANNEL_EDGE_ACTION_HOLD));
        ESP_ERROR_CHECK(pcnt_channel_set_level_action(channel, PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_KEEP));
        ESP_ERROR_CHECK(pcnt_unit_add_watch_point(wire_counter[i], 32767));
        ESP_ERROR_CHECK(pcnt_unit_add_watch_point(wire_counter[i], -32768));
        ESP_ERROR_CHECK(pcnt_unit_enable(wire_counter[i]));
    }
}

static void wire_probe_start(void)
{
    for (int i = 0; i < 3; i++) {
        ESP_ERROR_CHECK(pcnt_unit_clear_count(wire_counter[i]));
        ESP_ERROR_CHECK(pcnt_unit_start(wire_counter[i]));
    }
    atomic_store(&wire_us, 0);
    wire_started_us = esp_timer_get_time();
}

static void output_disable(void)
{
    ESP_ERROR_CHECK(i2s_channel_disable(tx));
    atomic_store(&wire_us, (uint32_t)(esp_timer_get_time() - wire_started_us));
    for (int i = 0; i < 3; i++) ESP_ERROR_CHECK(pcnt_unit_stop(wire_counter[i]));
    atomic_store(&output_active, false);
}
typedef struct {
    uint32_t generation;
    size_t bytes;
    int16_t samples[960];
} playback_block_t;

void audio_capture_set(bool enabled, uint32_t generation)
{
    atomic_store(&capturing, false);
    xQueueReset(capture_queue);
    atomic_store(&capture_generation, generation);
    atomic_store(&capturing, enabled);
}

void audio_stop(void)
{
    atomic_store(&capturing, false);
    atomic_fetch_add(&play_generation, 1);
    atomic_store(&ending, false);
    atomic_store(&played, false);
    xQueueReset(play_queue);
    xQueueReset(capture_queue);
}

void audio_play_start(void)
{
    audio_stop();
    atomic_store(&playback_underruns, 0);
    atomic_store(&output_bytes, 0);
    atomic_store(&output_peak, 0);
}

bool audio_play_push(const void *data, size_t bytes)
{
    if (!bytes || bytes > 1920 || bytes % 2) return false;
    playback_block_t block = {.generation = atomic_load(&play_generation), .bytes = bytes};
    memcpy(block.samples, data, bytes);
    return xQueueSend(play_queue, &block, 0) == pdTRUE;
}

void audio_play_end(void) { atomic_store(&ending, true); }
bool audio_take_played(void) { return atomic_exchange(&played, false); }
bool audio_output_active(void) { return atomic_load(&output_active); }
audio_stats_t audio_stats(void)
{
    int counts[3];
    for (int i = 0; i < 3; i++) ESP_ERROR_CHECK(pcnt_unit_get_count(wire_counter[i], &counts[i]));
    return (audio_stats_t){atomic_load(&output_bytes), atomic_load(&output_peak),
                           atomic_load(&playback_underruns), uxQueueMessagesWaiting(play_queue),
                           counts[0], counts[1], counts[2], atomic_load(&wire_us)};
}

static void capture_task(void *arg)
{
    static int32_t raw[640];
    static capture_block_t block;
    // INMP441 needs 2^18 clocks after startup: 256ms at 16k/64bit.
    int warmup = 20;
    while (true) {
        size_t bytes = 0;
        uint32_t generation = atomic_load(&capture_generation);
        esp_err_t result = i2s_channel_read(rx, raw, sizeof(raw), &bytes, 1000);
        if (result != ESP_OK || bytes != sizeof(raw)) {
            ESP_LOGW("capture", "Short/error read: %s, %u", esp_err_to_name(result), (unsigned)bytes);
            continue;
        }
        if (warmup > 0) { warmup--; continue; }
        if (!atomic_load(&capturing)) continue;
        block.generation = generation;
        // Stereo 32-bit slots, left 24-bit signed data aligned to MSBs.
        for (int i = 0; i < 320; i++) block.samples[i] = (int16_t)(raw[2 * i] >> 16);
        if (generation == atomic_load(&capture_generation) &&
            xQueueSend(capture_queue, &block, 0) != pdTRUE) {
            if (++capture_drops % 50 == 1) ESP_LOGW("capture", "Queue drops=%lu", (unsigned long)capture_drops);
        }
    }
}

static void playback_task(void *arg)
{
    static playback_block_t block;
    static int32_t stereo[1920];
    uint32_t generation = atomic_load(&play_generation);
    bool started = false;
    while (true) {
        uint32_t current = atomic_load(&play_generation);
        if (generation != current) {
            generation = current;
            started = false;
            if (atomic_load(&output_active)) output_disable();
        }
        unsigned queued = uxQueueMessagesWaiting(play_queue);
        if (!started && (queued >= 4 || (queued && atomic_load(&ending)))) {
            memset(stereo, 0, sizeof(stereo));
            size_t loaded;
            do {
                ESP_ERROR_CHECK(i2s_channel_preload_data(tx, stereo, sizeof(stereo), &loaded));
            } while (loaded == sizeof(stereo));
            wire_probe_start();
            ESP_ERROR_CHECK(i2s_channel_enable(tx));
            atomic_store(&output_active, true);
            started = true;
        }
        if (!started) {
            if (atomic_exchange(&ending, false)) atomic_store(&played, true);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        size_t bytes = sizeof(stereo);
        bool data = started && xQueueReceive(play_queue, &block, 0) == pdTRUE;
        if (data && block.generation != generation) continue;
        if (data) {
            for (size_t i = 0; i < block.bytes / 2; i++) {
                int16_t value = (int32_t)block.samples[i] * DAFE_VOLUME_PERCENT / 100;
                unsigned peak = value < 0 ? -(int)value : value;
                if (peak > atomic_load(&output_peak)) atomic_store(&output_peak, peak);
                // PCM16 at the MSBs of each 32-bit Philips I2S slot.
                int32_t slot = (int32_t)((uint32_t)(uint16_t)value << 16);
                stereo[2*i] = stereo[2*i+1] = slot;
            }
            bytes = block.bytes * 4;
        } else {
            memset(stereo, 0, sizeof(stereo));
            if (started && !atomic_load(&ending)) playback_underruns++;
        }
        size_t sent = 0;
        ESP_ERROR_CHECK(i2s_channel_write(tx, stereo, bytes, &sent, 1000));
        if (data) atomic_fetch_add(&output_bytes, sent / 4);
        if (sent != bytes) ESP_LOGW("playback", "Short DMA write");
        if (atomic_load(&ending) && uxQueueMessagesWaiting(play_queue) == 0) {
            // Drain with >DMA-depth of zeros before acknowledging audible completion.
            memset(stereo, 0, sizeof(stereo));
            for (int i = 0; i < 4; i++) ESP_ERROR_CHECK(i2s_channel_write(tx, stereo, sizeof(stereo), &sent, 1000));
            if (generation == atomic_load(&play_generation)) {
                atomic_store(&ending, false);
                atomic_store(&played, true);
                started = false;
                output_disable();
                ESP_LOGI("playback", "Drained; underruns=%lu", (unsigned long)playback_underruns);
            }
        }
    }
}

void audio_init(void)
{
    capture_queue = xQueueCreate(8, sizeof(capture_block_t));
    play_queue = xQueueCreate(16, sizeof(playback_block_t));
    assert(capture_queue && play_queue);
    i2s_chan_config_t rc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    i2s_chan_config_t tc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    tc.auto_clear = true;
    ESP_ERROR_CHECK(i2s_new_channel(&rc, NULL, &rx));
    ESP_ERROR_CHECK(i2s_new_channel(&tc, &tx, NULL));
    i2s_std_config_t mic = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.mclk = I2S_GPIO_UNUSED, .bclk = 26, .ws = 25, .dout = I2S_GPIO_UNUSED, .din = 34},
    };
    i2s_std_config_t speaker = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(48000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.mclk = I2S_GPIO_UNUSED, .bclk = 27, .ws = 14, .dout = 22, .din = I2S_GPIO_UNUSED},
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(rx, &mic));
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(tx, &speaker));
    wire_probe_init();
    ESP_ERROR_CHECK(i2s_channel_enable(rx));
    assert(xTaskCreate(capture_task, "capture", 4096, NULL, 6, NULL) == pdPASS);
    assert(xTaskCreate(playback_task, "playback", 4096, NULL, 7, NULL) == pdPASS);
}
