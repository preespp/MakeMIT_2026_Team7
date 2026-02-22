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
#define RX_ACCUM_SIZE      2048

// SAURON_UART_V1 binary frame (Jetson/FSM -> ESP32)
#define UART_FRAME_START   0xAA
#define UART_FRAME_END     0x55
#define UART_FRAME_VER_1   0x01
#define UART_FRAME_LEN_V1  8

// Servo pins
#define SERVO_PIN_1        18
#define SERVO_PIN_2        19
#define SERVO_PIN_3        21
#define SERVO_PIN_4        22

#define SERVO_FREQ         50
#define SERVO_RESOLUTION   LEDC_TIMER_16_BIT
#define SERVO_PERIOD_US    20000

// Calibrate these to your servo datasheet / measured travel.
// Many servos need wider than 1000-2000us to reach full motion.
#define SERVO_MIN_PULSE_US 500
#define SERVO_MAX_PULSE_US 2500
#define SERVO_MAX_ANGLE_DEG 180
#define SERVO_STEP_COUNT    40

#define MOVE_DURATION_MS   1000
#define SHAKE_COUNT        3
#define SHAKE_SPEED_MS     50

// Structure to store servo configuration
typedef struct {
    ledc_channel_t channel;
} servo_t;

servo_t servos[4];
static const int servo_pins[4] = {SERVO_PIN_1, SERVO_PIN_2, SERVO_PIN_3, SERVO_PIN_4};

// Helper: map angle to duty for LEDC
static uint32_t angle_to_duty(int angle)
{
    if (angle < 0) angle = 0;
    if (angle > SERVO_MAX_ANGLE_DEG) angle = SERVO_MAX_ANGLE_DEG;

    uint32_t pulse_us = SERVO_MIN_PULSE_US +
        ((uint32_t)angle * (SERVO_MAX_PULSE_US - SERVO_MIN_PULSE_US)) / SERVO_MAX_ANGLE_DEG;

    // Map pulse width (us) to LEDC duty over a 20 ms period.
    return (pulse_us * ((1U << 16) - 1)) / SERVO_PERIOD_US;
}

// Move servo 0->180->0
static void move_servo(servo_t* s)
{
    int steps = SERVO_STEP_COUNT;
    int step_delay = MOVE_DURATION_MS / (2 * steps);

    // 0 -> 180
    for (int i = 0; i <= steps; i++) {
        uint32_t duty = angle_to_duty((i * SERVO_MAX_ANGLE_DEG) / steps);
        ledc_set_duty(LEDC_HIGH_SPEED_MODE, s->channel, duty);
        ledc_update_duty(LEDC_HIGH_SPEED_MODE, s->channel);
        vTaskDelay(pdMS_TO_TICKS(step_delay));
    }

    // 180 -> 0
    for (int i = 0; i <= steps; i++) {
        uint32_t duty = angle_to_duty(SERVO_MAX_ANGLE_DEG - (i * SERVO_MAX_ANGLE_DEG) / steps);
        ledc_set_duty(LEDC_HIGH_SPEED_MODE, s->channel, duty);
        ledc_update_duty(LEDC_HIGH_SPEED_MODE, s->channel);
        vTaskDelay(pdMS_TO_TICKS(step_delay));
    }
}

// Map pill key to servo index
static int pill_to_index(const char* pill) {
    if (strcmp(pill, "Vitamin C") == 0) return 0;
    if (strcmp(pill, "Fish Oil") == 0) return 1;
    if (strcmp(pill, "Vitamin B") == 0) return 2;
    if (strcmp(pill, "Tylenol") == 0) return 3;
    return -1;
}

static void execute_channel_counts(const int counts[4]) {
    for (int idx = 0; idx < 4; idx++) {
        int count = counts[idx];
        if (count <= 0) continue;
        for (int i = 0; i < count; i++) {
            move_servo(&servos[idx]);
            vTaskDelay(pdMS_TO_TICKS(200)); // optional pause
        }
    }
}

static void send_ack_json(const char* status, const char* protocol, const int counts[4]) {
    char msg[160];
    int n = snprintf(
        msg,
        sizeof(msg),
        "{\"status\":\"%s\",\"protocol\":\"%s\",\"counts\":[%d,%d,%d,%d]}\n",
        status ? status : "done",
        protocol ? protocol : "unknown",
        counts[0], counts[1], counts[2], counts[3]
    );
    if (n > 0) {
        uart_write_bytes(UART_PORT_NUM, msg, (size_t)n);
    }
}

static void handle_json_command_line(char* line) {
    int counts[4] = {0, 0, 0, 0};
    if (!line) {
        send_ack_json("bad_json", "json_line", counts);
        return;
    }

    // Trim leading whitespace
    while (*line == ' ' || *line == '\t' || *line == '\r' || *line == '\n') {
        line++;
    }
    if (*line == '\0') {
        return;
    }

    cJSON* json = cJSON_Parse(line);
    if (!json) {
        send_ack_json("bad_json", "json_line", counts);
        return;
    }

    cJSON* item = NULL;
    cJSON_ArrayForEach(item, json) {
        if (!item || !item->string || !cJSON_IsNumber(item)) {
            continue;
        }
        int idx = pill_to_index(item->string);
        if (idx < 0) continue;
        int count = item->valueint;
        if (count < 0) count = 0;
        if (count > 20) count = 20;
        counts[idx] = count;
    }
    cJSON_Delete(json);

    execute_channel_counts(counts);
    send_ack_json("done", "json_line", counts);
}

static int try_handle_sauron_frame(const uint8_t* frame, size_t len) {
    if (!frame || len < UART_FRAME_LEN_V1) return 0;
    if (frame[0] != UART_FRAME_START) return 0;
    if (frame[UART_FRAME_LEN_V1 - 1] != UART_FRAME_END) return -1;

    uint8_t ver = frame[1];
    if (ver != UART_FRAME_VER_1) return -1;

    uint8_t checksum = (uint8_t)((frame[1] + frame[2] + frame[3] + frame[4] + frame[5]) & 0xFF);
    if (checksum != frame[6]) return -1;

    int counts[4] = { (int)frame[2], (int)frame[3], (int)frame[4], (int)frame[5] };
    execute_channel_counts(counts);
    send_ack_json("done", "SAURON_UART_V1", counts);
    return 1;
}

void uart_task(void* arg)
{
    uint8_t* data = (uint8_t*) malloc(BUF_SIZE);
    uint8_t* rx_buf = (uint8_t*) malloc(RX_ACCUM_SIZE);
    size_t rx_len = 0;
    if (!data || !rx_buf) {
        if (data) free(data);
        if (rx_buf) free(rx_buf);
        vTaskDelete(NULL);
        return;
    }

    while (1) {
        int len = uart_read_bytes(UART_PORT_NUM, data, BUF_SIZE - 1, pdMS_TO_TICKS(100));
        if (len > 0) {
            // Append to accumulation buffer (drop oldest on overflow).
            if ((size_t)len > RX_ACCUM_SIZE) {
                len = RX_ACCUM_SIZE;
                memcpy(rx_buf, &data[len - RX_ACCUM_SIZE], RX_ACCUM_SIZE);
                rx_len = RX_ACCUM_SIZE;
            } else {
                if (rx_len + (size_t)len > RX_ACCUM_SIZE) {
                    size_t overflow = (rx_len + (size_t)len) - RX_ACCUM_SIZE;
                    if (overflow >= rx_len) {
                        rx_len = 0;
                    } else {
                        memmove(rx_buf, rx_buf + overflow, rx_len - overflow);
                        rx_len -= overflow;
                    }
                }
                memcpy(rx_buf + rx_len, data, (size_t)len);
                rx_len += (size_t)len;
            }

            // Parse as many messages as possible from the buffer.
            while (rx_len > 0) {
                // Path A: binary frame starts with 0xAA
                if (rx_buf[0] == UART_FRAME_START) {
                    if (rx_len < UART_FRAME_LEN_V1) {
                        break; // wait for more bytes
                    }
                    int frame_result = try_handle_sauron_frame(rx_buf, rx_len);
                    if (frame_result > 0) {
                        memmove(rx_buf, rx_buf + UART_FRAME_LEN_V1, rx_len - UART_FRAME_LEN_V1);
                        rx_len -= UART_FRAME_LEN_V1;
                        continue;
                    }
                    // Invalid frame start or bad checksum/version/end; drop one byte and resync.
                    memmove(rx_buf, rx_buf + 1, rx_len - 1);
                    rx_len -= 1;
                    continue;
                }

                // Path B: newline-delimited JSON (legacy compatibility).
                uint8_t* newline = (uint8_t*)memchr(rx_buf, '\n', rx_len);
                if (!newline) {
                    // No newline yet. Drop leading non-JSON noise to avoid buffer clogging.
                    if (rx_buf[0] != '{' && rx_buf[0] != ' ' && rx_buf[0] != '\t' && rx_buf[0] != '\r') {
                        memmove(rx_buf, rx_buf + 1, rx_len - 1);
                        rx_len -= 1;
                        continue;
                    }
                    break;
                }

                size_t line_len = (size_t)(newline - rx_buf);
                char line[BUF_SIZE];
                size_t copy_len = (line_len < (BUF_SIZE - 1)) ? line_len : (BUF_SIZE - 1);
                memcpy(line, rx_buf, copy_len);
                line[copy_len] = '\0';

                // Consume line (+ newline) before handling to keep parser state simple.
                size_t consume = line_len + 1;
                memmove(rx_buf, rx_buf + consume, rx_len - consume);
                rx_len -= consume;

                handle_json_command_line(line);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    free(data);
    free(rx_buf);
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
            .gpio_num = servo_pins[i],
            .speed_mode = LEDC_HIGH_SPEED_MODE,
            .hpoint = 0,
            .timer_sel = LEDC_TIMER_0
        };
        ledc_channel_config(&ledc_channel);
    }

    // Start UART task
    xTaskCreate(uart_task, "uart_task", 4096, NULL, 10, NULL);
}
