#include "audio_io.h"
#include "network.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "diagnostics.h"

void app_main(void)
{
    // Never erase an existing NVS partition automatically.
    ESP_ERROR_CHECK(nvs_flash_init());
    audio_init();
    ESP_LOGI("dafe", "Audio ready: INMP441 26/25/34; MAX98357A 27/14/22");
    network_start();
    diagnostics_start();
}
