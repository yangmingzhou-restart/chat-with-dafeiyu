idf_component_register(SRCS "app_main.c" "audio_io.c" "network.c" "diagnostics.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_i2s esp_driver_uart esp_driver_pcnt esp_driver_gpio esp_wifi esp_netif nvs_flash esp_event esp_websocket_client json esp_timer)
