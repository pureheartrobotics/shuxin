#include "platform.h"
#include "driver/i2c_master.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static i2c_master_dev_handle_t s_dev;

void vl53l5cx_bind_i2c(i2c_master_bus_handle_t bus) {
    i2c_device_config_t dev = {0};
    dev.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    dev.device_address = 0x29;
    dev.scl_speed_hz = 400000;
    ESP_ERROR_CHECK(i2c_master_bus_add_device(bus, &dev, &s_dev));
}

static uint8_t i2c_write(uint16_t reg, uint8_t *data, uint32_t size) {
    enum { kChunk = 128 };
    uint8_t buf[kChunk + 2];
    uint32_t offset = 0;
    while (offset < size) {
        uint32_t n = size - offset;
        if (n > kChunk) n = kChunk;
        buf[0] = (uint8_t)((reg + offset) >> 8);
        buf[1] = (uint8_t)(reg + offset);
        memcpy(buf + 2, data + offset, n);
        if (i2c_master_transmit(s_dev, buf, n + 2, 1000) != ESP_OK) return 1;
        offset += n;
    }
    return 0;
}

static uint8_t i2c_read(uint16_t reg, uint8_t *data, uint32_t size) {
    uint8_t addr[2] = { (uint8_t)(reg >> 8), (uint8_t)reg };
    if (i2c_master_transmit_receive(s_dev, addr, 2, data, size, 1000) != ESP_OK) return 1;
    return 0;
}

uint8_t RdByte(VL53L5CX_Platform *p_platform, uint16_t RegisterAdress, uint8_t *p_value) {
    (void)p_platform;
    return i2c_read(RegisterAdress, p_value, 1);
}

uint8_t WrByte(VL53L5CX_Platform *p_platform, uint16_t RegisterAdress, uint8_t value) {
    (void)p_platform;
    return i2c_write(RegisterAdress, &value, 1);
}

uint8_t WrMulti(VL53L5CX_Platform *p_platform, uint16_t RegisterAdress, uint8_t *p_values, uint32_t size) {
    (void)p_platform;
    return i2c_write(RegisterAdress, p_values, size);
}

uint8_t RdMulti(VL53L5CX_Platform *p_platform, uint16_t RegisterAdress, uint8_t *p_values, uint32_t size) {
    (void)p_platform;
    return i2c_read(RegisterAdress, p_values, size);
}

void SwapBuffer(uint8_t *buffer, uint16_t size) {
    for (uint16_t i = 0; i < size; i = (uint16_t)(i + 4)) {
        uint32_t tmp = ((uint32_t)buffer[i] << 24) | ((uint32_t)buffer[i + 1] << 16) |
            ((uint32_t)buffer[i + 2] << 8) | buffer[i + 3];
        memcpy(&buffer[i], &tmp, 4);
    }
}

uint8_t WaitMs(VL53L5CX_Platform *p_platform, uint32_t TimeMs) {
    (void)p_platform;
    vTaskDelay(pdMS_TO_TICKS(TimeMs));
    return 0;
}
