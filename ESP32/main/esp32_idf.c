#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "cJSON.h"

#define UART_PORT_NUM      UART_NUM_0
#define UART_BAUD_RATE     115200
#define UART_RX_PIN        UART_PIN_NO_CHANGE
#define UART_TX_PIN        UART_PIN_NO_CHANGE
#define BUF_SIZE           1024

// Servo pins
#define SERVO_PIN_1        18
#define SERVO_PIN_2        19
#define SERVO_PIN_3        21
#define SERVO_PIN_4        22

#define SERVO_FREQ         50
#define SERVO_RESOLUTION   LEDC_TIMER_16_BIT

#define MOVE_DURATION_MS   1000
#define SHAKE_COUNT        3
#define SHAKE_SPEED_MS     50

// Structure to store servo configuration
typedef struct {
    ledc_channel_t channel;
} servo_t;

servo_t servos[4];

// Helper: map angle to duty for LEDC
static uint32_t angle_to_duty(int angle)
{
    // 0° -> 1ms, 180° -> 2ms on 20ms period
    // Duty range: 0 - 2^16-1
    uint32_t min_duty = (uint32_t)((65535 * 1) / 20); // 1 ms
    uint32_t max_duty = (uint32_t)((65535 * 2) / 20); // 2 ms
    return min_duty + (angle * (max_duty - min_duty)) / 180;
}

// Move servo 0->180->0
static void move_servo(servo_t* s)
{
    int steps = 20;
    int step_delay = MOVE_DURATION_MS / (2 * steps);

    // 0 -> 180
    for (int i = 0; i <= steps; i++) {
        uint32_t duty = angle_to_duty((i * 180) / steps);
        ledc_set_duty(LEDC_HIGH_SPEED_MODE, s->channel, duty);
        ledc_update_duty(LEDC_HIGH_SPEED_MODE, s->channel);
        vTaskDelay(pdMS_TO_TICKS(step_delay));
    }

    // 180 -> 0
    for (int i = 0; i <= steps; i++) {
        uint32_t duty = angle_to_duty(180 - (i * 180) / steps);
        ledc_set_duty(LEDC_HIGH_SPEED_MODE, s->channel, duty);
        ledc_update_duty(LEDC_HIGH_SPEED_MODE, s->channel);
        vTaskDelay(pdMS_TO_TICKS(step_delay));
    }

    // Shake after each move
    for (int i = 0; i < SHAKE_COUNT; i++) {
        ledc_set_duty(LEDC_HIGH_SPEED_MODE, s->channel, angle_to_duty(0));
        ledc_update_duty(LEDC_HIGH_SPEED_MODE, s->channel);
        vTaskDelay(pdMS_TO_TICKS(SHAKE_SPEED_MS));
        ledc_set_duty(LEDC_HIGH_SPEED_MODE, s->channel, angle_to_duty(20));
        ledc_update_duty(LEDC_HIGH_SPEED_MODE, s->channel);
        vTaskDelay(pdMS_TO_TICKS(SHAKE_SPEED_MS));
    }
    // Return to 0
    ledc_set_duty(LEDC_HIGH_SPEED_MODE, s->channel, angle_to_duty(0));
    ledc_update_duty(LEDC_HIGH_SPEED_MODE, s->channel);
}

// Map pill key to servo index
static int pill_to_index(const char* pill) {
    if (strcmp(pill, "pill1") == 0) return 0;
    if (strcmp(pill, "pill2") == 0) return 1;
    if (strcmp(pill, "pill3") == 0) return 2;
    if (strcmp(pill, "pill4") == 0) return 3;
    return -1;
}

void uart_task(void* arg)
{
    uint8_t* data = (uint8_t*) malloc(BUF_SIZE);
    while (1) {
        int len = uart_read_bytes(UART_PORT_NUM, data, BUF_SIZE - 1, pdMS_TO_TICKS(100));
        if (len > 0) {
            data[len] = 0; // Null terminate
            // Parse JSON
            cJSON* json = cJSON_Parse((char*)data);
            if (json) {
                cJSON* item = NULL;
                cJSON_ArrayForEach(item, json) {
                    const char* key = item->string;
                    int count = item->valueint;
                    int idx = pill_to_index(key);
                    if (idx >= 0 && count > 0) {
                        for (int i = 0; i < count; i++) {
                            move_servo(&servos[idx]);
                            vTaskDelay(pdMS_TO_TICKS(200)); // optional pause
                        }
                    }
                }
                cJSON_Delete(json);

                // Send confirmation
                const char* done_msg = "{\"status\":\"done\"}\n";
                uart_write_bytes(UART_PORT_NUM, done_msg, strlen(done_msg));
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    free(data);
}

void app_main(void)
{
    // Using the board's USB cable means the USB-UART bridge is connected to UART0.
    // Silence app logs so JSON replies are not mixed with log lines on the same port.
    esp_log_level_set("*", ESP_LOG_NONE);

    // Configure UART
    uart_config_t uart_config = {
        .baud_rate = UART_BAUD_RATE,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
    };
    uart_driver_install(UART_PORT_NUM, BUF_SIZE * 2, 0, 0, NULL, 0);
    uart_param_config(UART_PORT_NUM, &uart_config);
    uart_set_pin(UART_PORT_NUM, UART_TX_PIN, UART_RX_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);

    // Configure LEDC for servos
    ledc_timer_config_t ledc_timer = {
        .speed_mode = LEDC_HIGH_SPEED_MODE,
        .duty_resolution = SERVO_RESOLUTION,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = SERVO_FREQ,
        .clk_cfg = LEDC_AUTO_CLK
    };
    ledc_timer_config(&ledc_timer);

    // Attach servos to channels
    for (int i = 0; i < 4; i++) {
        servos[i].channel = (ledc_channel_t)i;
        ledc_channel_config_t ledc_channel = {
            .channel = servos[i].channel,
            .duty = angle_to_duty(0),
            .gpio_num = SERVO_PIN_1 + i, // pins 18,19,21,22
            .speed_mode = LEDC_HIGH_SPEED_MODE,
            .hpoint = 0,
            .timer_sel = LEDC_TIMER_0
        };
        ledc_channel_config(&ledc_channel);
    }

    // Start UART task
    xTaskCreate(uart_task, "uart_task", 4096, NULL, 10, NULL);
}
