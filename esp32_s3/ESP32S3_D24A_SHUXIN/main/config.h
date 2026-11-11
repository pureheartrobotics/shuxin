#pragma once
#include "driver/gpio.h"
// ESP32-S3-N16R8 DevKitC-1 直连 D24A；GPIO 与接线表一致。
constexpr gpio_num_t MOTOR_PWMA_GPIO = GPIO_NUM_4;
constexpr gpio_num_t MOTOR_AIN1_GPIO = GPIO_NUM_5;
constexpr gpio_num_t MOTOR_AIN2_GPIO = GPIO_NUM_6;
constexpr gpio_num_t MOTOR_PWMB_GPIO = GPIO_NUM_7;
constexpr gpio_num_t MOTOR_BIN1_GPIO = GPIO_NUM_15;
constexpr gpio_num_t MOTOR_BIN2_GPIO = GPIO_NUM_16;
constexpr gpio_num_t MOTOR_PWMC_GPIO = GPIO_NUM_9;
constexpr gpio_num_t MOTOR_CIN1_GPIO = GPIO_NUM_10;
constexpr gpio_num_t MOTOR_CIN2_GPIO = GPIO_NUM_11;
constexpr gpio_num_t MOTOR_PWMD_GPIO = GPIO_NUM_12;
constexpr gpio_num_t MOTOR_DIN1_GPIO = GPIO_NUM_21;
constexpr gpio_num_t MOTOR_DIN2_GPIO = GPIO_NUM_14;
constexpr gpio_num_t MOTOR_STBY_GPIO = GPIO_NUM_8;
constexpr int MOTOR_PWM_FREQUENCY_HZ = 10000;
constexpr int MOTOR_DEFAULT_SPEED_PERCENT = 70;
constexpr int64_t MOTION_TIMEOUT_US = 4000000;
constexpr int64_t BRAKE_DURATION_US = 50000;
// A/C=左侧，B/D=右侧；右侧镜像安装，与二驱 C3 默认一致。
constexpr bool MOTOR_INVERT_A = false;
constexpr bool MOTOR_INVERT_B = true;
constexpr bool MOTOR_INVERT_C = false;
constexpr bool MOTOR_INVERT_D = true;
constexpr int CONTROL_UART_TX = 17;
constexpr int CONTROL_UART_RX = 18;
// 颈部 MG996R：水平 GPIO1、俯仰 GPIO2（已验证）。舵机红线 5–6V，不要接 12V。
constexpr gpio_num_t SERVO_PAN_GPIO = GPIO_NUM_1;
constexpr gpio_num_t SERVO_TILT_GPIO = GPIO_NUM_2;
constexpr int DEBUG_UART_TX = 43;
constexpr int DEBUG_UART_RX = 44;
constexpr int CONTROL_UART_BAUD = 115200;
