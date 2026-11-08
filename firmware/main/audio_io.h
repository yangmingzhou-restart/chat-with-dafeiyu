#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

typedef struct {
    uint32_t generation;
    int16_t samples[320];
} capture_block_t;

extern QueueHandle_t capture_queue;
void audio_init(void);
void audio_capture_set(bool enabled, uint32_t generation);
void audio_play_start(void);
bool audio_play_push(const void *data, size_t bytes);
void audio_play_end(void);
void audio_stop(void);
bool audio_take_played(void);
bool audio_output_active(void);
typedef struct {
    uint32_t bytes, peak, underruns, queued;
    uint32_t bclk_edges, lrclk_edges, din_edges, wire_us;
} audio_stats_t;
audio_stats_t audio_stats(void);
