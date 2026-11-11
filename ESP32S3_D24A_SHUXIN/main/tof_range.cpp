#include <stdio.h>
#include <string.h>
#include "driver/i2c_master.h"
#include "driver/uart.h"
#include "driver/usb_serial_jtag.h"
extern "C" {
#include "vl53l5cx_api.h"
void vl53l5cx_bind_i2c(i2c_master_bus_handle_t bus);
}

static VL53L5CX_Configuration s_dev{};
static bool s_ready = false;

static void ToFReply(const char *msg) {
    usb_serial_jtag_write_bytes(msg, strlen(msg), 0);
    uart_write_bytes(UART_NUM_1, msg, strlen(msg));
}

void InitTofRange(i2c_master_bus_handle_t bus) {
    vl53l5cx_bind_i2c(bus);
    s_dev.platform.address = VL53L5CX_DEFAULT_I2C_ADDRESS;
    uint8_t alive = 0;
    uint8_t st = vl53l5cx_is_alive(&s_dev, &alive);
    char msg[64];
    if (st || !alive) {
        snprintf(msg, sizeof(msg), "TOF INIT FAIL alive=%u st=%u\r\n", alive, st);
        ToFReply(msg);
        return;
    }
    st = vl53l5cx_init(&s_dev);
    if (st) {
        snprintf(msg, sizeof(msg), "TOF FW FAIL st=%u\r\n", st);
        ToFReply(msg);
        return;
    }
    vl53l5cx_set_resolution(&s_dev, VL53L5CX_RESOLUTION_4X4);
    vl53l5cx_set_ranging_frequency_hz(&s_dev, 10);
    st = vl53l5cx_start_ranging(&s_dev);
    if (st) {
        snprintf(msg, sizeof(msg), "TOF START FAIL st=%u\r\n", st);
        ToFReply(msg);
        return;
    }
    s_ready = true;
    ToFReply("TOF RANGING\r\n");
}

void PollTof() {
    if (!s_ready) return;
    uint8_t ready = 0;
    if (vl53l5cx_check_data_ready(&s_dev, &ready) || !ready) return;
    VL53L5CX_ResultsData data{};
    if (vl53l5cx_get_ranging_data(&s_dev, &data)) return;
    int mm = data.distance_mm[5];
    int status = data.target_status[5];
    char msg[48];
    snprintf(msg, sizeof(msg), "TOF %dmm st=%d\r\n", mm, status);
    ToFReply(msg);
}
