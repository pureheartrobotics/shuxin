// 从 C3 Tb6612Chassis 扩到 D24A 四路；单任务独占电机与截止时间。
#include "config.h"
#include "command.h"
#include "neck.h"
#include <stdio.h>
#include <string.h>
#include "driver/ledc.h"
#include "driver/uart.h"
#include "driver/usb_serial_jtag.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

enum class Io { Uart1, Uart0, Usb };
constexpr uart_port_t kUart1 = UART_NUM_1;
constexpr uart_port_t kUart0 = UART_NUM_0;
constexpr ledc_channel_t kChannelA = LEDC_CHANNEL_0, kChannelB = LEDC_CHANNEL_1;
constexpr ledc_channel_t kChannelC = LEDC_CHANNEL_2, kChannelD = LEDC_CHANNEL_3;
constexpr uint32_t kMaxDuty = 1023;

class Tb6612Chassis {
public:
    void Initialize() {
        gpio_config_t io{};
        io.pin_bit_mask = (1ULL << MOTOR_AIN1_GPIO) | (1ULL << MOTOR_AIN2_GPIO) |
            (1ULL << MOTOR_BIN1_GPIO) | (1ULL << MOTOR_BIN2_GPIO) |
            (1ULL << MOTOR_CIN1_GPIO) | (1ULL << MOTOR_CIN2_GPIO) |
            (1ULL << MOTOR_DIN1_GPIO) | (1ULL << MOTOR_DIN2_GPIO) |
            (1ULL << MOTOR_STBY_GPIO);
        io.mode = GPIO_MODE_OUTPUT;
        io.pull_down_en = GPIO_PULLDOWN_ENABLE;
        ESP_ERROR_CHECK(gpio_config(&io));
        ESP_ERROR_CHECK(gpio_set_level(MOTOR_STBY_GPIO, 0));
        ledc_timer_config_t timer{};
        timer.speed_mode = LEDC_LOW_SPEED_MODE;
        timer.duty_resolution = LEDC_TIMER_10_BIT;
        timer.timer_num = LEDC_TIMER_0;
        timer.freq_hz = MOTOR_PWM_FREQUENCY_HZ;
        timer.clk_cfg = LEDC_AUTO_CLK;
        ESP_ERROR_CHECK(ledc_timer_config(&timer));
        ConfigureChannel(kChannelA, MOTOR_PWMA_GPIO);
        ConfigureChannel(kChannelB, MOTOR_PWMB_GPIO);
        ConfigureChannel(kChannelC, MOTOR_PWMC_GPIO);
        ConfigureChannel(kChannelD, MOTOR_PWMD_GPIO);
        PowerDown();
    }

    void Execute(const Command &command) {
        if (command.action == Action::Stop || command.speed == 0) { Stop(); return; }
        int left, right;
        WheelSpeeds(command.action, command.speed, left, right);
        const int a = MOTOR_INVERT_A ? -left : left;
        const int b = MOTOR_INVERT_B ? -right : right;
        const int c = MOTOR_INVERT_C ? -left : left;
        const int d = MOTOR_INVERT_D ? -right : right;
        // 同方向刷新不切断PWM；方向变化先撤掉使能，避免带电换向。
        if (!moving_ || ((a > 0) != (left_ > 0)) || ((b > 0) != (right_ > 0))) {
            PowerDown();
            vTaskDelay(pdMS_TO_TICKS(2));
            SetDirection(MOTOR_AIN1_GPIO, MOTOR_AIN2_GPIO, a);
            SetDirection(MOTOR_BIN1_GPIO, MOTOR_BIN2_GPIO, b);
            SetDirection(MOTOR_CIN1_GPIO, MOTOR_CIN2_GPIO, c);
            SetDirection(MOTOR_DIN1_GPIO, MOTOR_DIN2_GPIO, d);
        }
        SetPwm(command.speed);
        ESP_ERROR_CHECK(gpio_set_level(MOTOR_STBY_GPIO, 1));
        left_ = a; right_ = b;
        moving_ = true; braking_ = false;
        deadline_us_ = esp_timer_get_time() + MOTION_TIMEOUT_US;
    }

    // 50ms短路刹车后转高阻待机；重复S不会延长刹车。
    void Stop() {
        if (!moving_) return;
        ESP_ERROR_CHECK(gpio_set_level(MOTOR_STBY_GPIO, 0));
        SetPwm(0);
        const gpio_num_t pins[] = {
            MOTOR_AIN1_GPIO, MOTOR_AIN2_GPIO, MOTOR_BIN1_GPIO, MOTOR_BIN2_GPIO,
            MOTOR_CIN1_GPIO, MOTOR_CIN2_GPIO, MOTOR_DIN1_GPIO, MOTOR_DIN2_GPIO};
        for (auto pin : pins)
            ESP_ERROR_CHECK(gpio_set_level(pin, 1));
        WriteDuty(1024);
        ESP_ERROR_CHECK(gpio_set_level(MOTOR_STBY_GPIO, 1));
        moving_ = false; braking_ = true;
        deadline_us_ = esp_timer_get_time() + BRAKE_DURATION_US;
    }

    void Poll() {
        if (esp_timer_get_time() < deadline_us_) return;
        if (moving_) Stop();
        else if (braking_) PowerDown();
    }
    const char *State() const { return moving_ ? "moving" : (braking_ ? "braking" : "stopped"); }

private:
    bool moving_ = false, braking_ = false;
    int left_ = 0, right_ = 0;
    int64_t deadline_us_ = 0;
    void ConfigureChannel(ledc_channel_t channel, gpio_num_t pin) {
        ledc_channel_config_t cfg{};
        cfg.gpio_num = pin;
        cfg.speed_mode = LEDC_LOW_SPEED_MODE;
        cfg.channel = channel;
        cfg.timer_sel = LEDC_TIMER_0;
        ESP_ERROR_CHECK(ledc_channel_config(&cfg));
    }
    void WriteDuty(uint32_t duty) {
        const ledc_channel_t channels[] = {kChannelA, kChannelB, kChannelC, kChannelD};
        for (auto channel : channels) {
            ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, channel, duty));
            ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, channel));
        }
    }
    void SetPwm(int percent) { WriteDuty(kMaxDuty * percent / 100); }
    void SetDirection(gpio_num_t in1, gpio_num_t in2, int speed) {
        ESP_ERROR_CHECK(gpio_set_level(in1, speed > 0));
        ESP_ERROR_CHECK(gpio_set_level(in2, speed < 0));
    }
    void PowerDown() {
        ESP_ERROR_CHECK(gpio_set_level(MOTOR_STBY_GPIO, 0));
        SetPwm(0);
        const gpio_num_t pins[] = {
            MOTOR_AIN1_GPIO, MOTOR_AIN2_GPIO, MOTOR_BIN1_GPIO, MOTOR_BIN2_GPIO,
            MOTOR_CIN1_GPIO, MOTOR_CIN2_GPIO, MOTOR_DIN1_GPIO, MOTOR_DIN2_GPIO};
        for (auto pin : pins)
            ESP_ERROR_CHECK(gpio_set_level(pin, 0));
        moving_ = braking_ = false;
        left_ = right_ = 0;
        deadline_us_ = 0;
    }
};

void Reply(Io io, const char *message) {
    if (io == Io::Usb) usb_serial_jtag_write_bytes(message, strlen(message), 0);
    else if (io == Io::Uart0) uart_write_bytes(kUart0, message, strlen(message));
    else uart_write_bytes(kUart1, message, strlen(message));
}

struct LineReader {
    char line[96]{};
    size_t length = 0;
    bool discard = false;
    Neck *neck = nullptr;
    void Feed(char c, Io io, Tb6612Chassis &chassis) {
        if (c == '\n') {
            if (discard) Reply(io, "ERR LINE\r\n");
            else if (length) {
                line[length] = '\0';
                char work[96];
                memcpy(work, line, length + 1);
                HeadCommand head{};
                Command command{};
                if (neck && ParseHead(work, head)) {
                    neck->Execute(head);
                    Reply(io, "OK head\r\n");
                } else if (ParseCommand(line, MOTOR_DEFAULT_SPEED_PERCENT, command)) {
                    chassis.Execute(command);
                    char response[48];
                    snprintf(response, sizeof(response), "OK %s\r\n", chassis.State());
                    Reply(io, response);
                } else Reply(io, "ERR COMMAND\r\n");
            }
            length = 0; discard = false;
        } else if (c != '\r' && !discard) {
            if (c == '\0' || length >= sizeof(line)-1) discard = true;
            else line[length++] = c;
        }
    }
};

static void InstallUart(uart_port_t port, int tx, int rx) {
    uart_config_t uart{};
    uart.baud_rate = CONTROL_UART_BAUD;
    uart.data_bits = UART_DATA_8_BITS;
    uart.parity = UART_PARITY_DISABLE;
    uart.stop_bits = UART_STOP_BITS_1;
    uart.flow_ctrl = UART_HW_FLOWCTRL_DISABLE;
    uart.source_clk = UART_SCLK_DEFAULT;
    ESP_ERROR_CHECK(uart_param_config(port, &uart));
    ESP_ERROR_CHECK(uart_set_pin(port, tx, rx, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(port, 512, 0, 0, nullptr, 0));
}

extern "C" void app_main() {
    // 驱动初始化在串口之前；上电不自动运行。
    Tb6612Chassis chassis;
    chassis.Initialize();
    Neck neck;
    neck.Initialize();
    InstallUart(kUart1, CONTROL_UART_TX, CONTROL_UART_RX);
    InstallUart(kUart0, DEBUG_UART_TX, DEBUG_UART_RX);
    usb_serial_jtag_driver_config_t usb{};
    usb.tx_buffer_size = 512; usb.rx_buffer_size = 512;
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
    Reply(Io::Uart1, "READY F/B/L/R/S HEAD NOD SHAKE\r\n");
    Reply(Io::Uart0, "READY F/B/L/R/S HEAD NOD SHAKE\r\n");
    Reply(Io::Usb, "READY F/B/L/R/S HEAD NOD SHAKE\r\n");
    LineReader uart1_reader, uart0_reader, usb_reader;
    uart1_reader.neck = uart0_reader.neck = usb_reader.neck = &neck;
    uint8_t bytes[64];
    while (true) {
        chassis.Poll();
        neck.Poll();
        int count = uart_read_bytes(kUart1, bytes, sizeof(bytes), 0);
        for (int i=0; i<count; ++i) uart1_reader.Feed(bytes[i], Io::Uart1, chassis);
        count = uart_read_bytes(kUart0, bytes, sizeof(bytes), 0);
        for (int i=0; i<count; ++i) uart0_reader.Feed(bytes[i], Io::Uart0, chassis);
        count = usb_serial_jtag_read_bytes(bytes, sizeof(bytes), 0);
        for (int i=0; i<count; ++i) usb_reader.Feed(bytes[i], Io::Usb, chassis);
        chassis.Poll();
        neck.Poll();
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
