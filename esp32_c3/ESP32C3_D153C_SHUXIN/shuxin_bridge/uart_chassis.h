#pragma once
#include <algorithm>
#include <mutex>
#include <cstdio>
#include <cstring>
#include "driver/uart.h"
#include "cJSON.h"

// 替换原S3板的本地电机类；通过P2的GPIO5/9发送命令到C3。
// UART写入成功只表示已发送；返回值不冒充下位机执行确认。
class Tb6612Chassis {
public:
    Tb6612Chassis() {
        uart_config_t cfg{};
        cfg.baud_rate = 115200;
        cfg.data_bits = UART_DATA_8_BITS;
        cfg.parity = UART_PARITY_DISABLE;
        cfg.stop_bits = UART_STOP_BITS_1;
        cfg.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
        cfg.source_clk = UART_SCLK_DEFAULT;
        ESP_ERROR_CHECK(uart_param_config(kPort, &cfg));
        ESP_ERROR_CHECK(uart_set_pin(kPort, 5, 9, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
        ESP_ERROR_CHECK(uart_driver_install(kPort, 512, 0, 0, nullptr, 0));
        Stop();
    }
    void Forward(int speed) { Send('F', speed); }
    void Backward(int speed) { Send('B', speed); }
    void TurnLeft(int speed) { Send('L', speed); }
    void TurnRight(int speed) { Send('R', speed); }
    void Stop() { Send('S', 0); }
    cJSON *GetResult(const char *action) const {
        std::lock_guard<std::mutex> lock(mutex_);
        cJSON *result = cJSON_CreateObject();
        cJSON_AddBoolToObject(result, "accepted", sent_);
        cJSON_AddStringToObject(result, "action", action);
        cJSON_AddStringToObject(result, "state", sent_ ? "command_sent" : "send_failed");
        cJSON_AddBoolToObject(result, "execution_confirmed", false);
        return result;
    }
private:
    static constexpr uart_port_t kPort = UART_NUM_1;
    mutable std::mutex mutex_;
    bool sent_ = false;
    void Send(char action, int speed) {
        std::lock_guard<std::mutex> lock(mutex_);
        char command[24];
        int length = action == 'S' ? snprintf(command, sizeof(command), "S\n") :
            snprintf(command, sizeof(command), "%c %d\n", action, std::clamp(speed, 0, 100));
        sent_ = uart_write_bytes(kPort, command, length) == length;
    }
};
