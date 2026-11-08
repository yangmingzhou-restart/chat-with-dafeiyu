#include "diagnostics.h"
#include "audio_io.h"
#include "network.h"
#include <stdio.h>
#include "driver/uart.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_heap_caps.h"

static void record(void)
{
    static capture_block_t block;
    static char line[1291];
    static const char hex[] = "0123456789abcdef";
    audio_stop();
    audio_capture_set(true, UINT32_MAX);
    printf("DAFE_PCM_BEGIN 16000 250\n");
    unsigned count = 0;
    while (count < 250 && xQueueReceive(capture_queue, &block, pdMS_TO_TICKS(1000)) == pdTRUE) {
        if (block.generation != UINT32_MAX) continue;
        const unsigned char *bytes = (const unsigned char *)block.samples;
        for (int i = 0; i < 640; i++) {
            line[2*i] = hex[bytes[i] >> 4];
            line[2*i+1] = hex[bytes[i] & 15];
        }
        line[1280] = '\n';
        fwrite("DAFE_PCM ", 1, 9, stdout);
        fwrite(line, 1, 1281, stdout);
        count++;
    }
    audio_capture_set(false, UINT32_MAX);
    printf("DAFE_PCM_END %u\n", count);
}

static void diagnostic_task(void *arg)
{
    unsigned char command;
    while (true) {
        if (uart_read_bytes(UART_NUM_0, &command, 1, pdMS_TO_TICKS(100)) != 1) continue;
        if (command == 's') {
            audio_stats_t stats = audio_stats();
            printf("DAFE_STATUS heap=%u network=%d speaker=%d bytes=%lu peak=%lu underruns=%lu queued=%lu bclk=%lu lrclk=%lu din=%lu wire_us=%lu\n",
                   (unsigned)esp_get_free_heap_size(), network_busy(), audio_output_active(),
                   (unsigned long)stats.bytes, (unsigned long)stats.peak,
                   (unsigned long)stats.underruns, (unsigned long)stats.queued,
                   (unsigned long)stats.bclk_edges, (unsigned long)stats.lrclk_edges,
                   (unsigned long)stats.din_edges, (unsigned long)stats.wire_us);
        }
        if (command == 't') printf("DAFE_TEST_TONE_DISABLED\n");
        if (command == 'r' && !network_busy()) record();
    }
}

void diagnostics_start(void)
{
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
    assert(xTaskCreate(diagnostic_task, "diagnostics", 4096, NULL, 4, NULL) == pdPASS);
    ESP_LOGI("diagnostics", "USB commands ready: s=status r=5s capture; test tones disabled; UART=%d", CONFIG_ESP_CONSOLE_UART_BAUDRATE);
}
