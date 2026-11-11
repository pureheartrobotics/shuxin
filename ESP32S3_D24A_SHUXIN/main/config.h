#pragma once
#include "driver/gpio.h"
// 按实车接线表：S3 DevKitC-1 直连 D24A，无 5V 缓冲器。ToF 已迁 K11C。
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
// 实车：C 左前、B 右前、D 左后、A 右后。左侧=C+D，右侧=B+A；右侧镜像。
constexpr bool MOTOR_INVERT_A = true;   // 右后
constexpr bool MOTOR_INVERT_B = true;   // 右前
constexpr bool MOTOR_INVERT_C = false;  // 左前
constexpr bool MOTOR_INVERT_D = false;  // 左后
constexpr int CONTROL_UART_TX = 17;
constexpr int CONTROL_UART_RX = 18;
constexpr int CONTROL_UART_BAUD = 115200;
constexpr gpio_num_t SERVO_PAN_GPIO = GPIO_NUM_1;
constexpr gpio_num_t SERVO_TILT_GPIO = GPIO_NUM_2;
// 四轮正交。勿用 GPIO48(RGB)、19/20(USB)、33-37(PSRAM)
constexpr gpio_num_t ENC_A_A_GPIO = GPIO_NUM_46;  // E1A 右后
constexpr gpio_num_t ENC_A_B_GPIO = GPIO_NUM_3;   // E1B
constexpr gpio_num_t ENC_B_A_GPIO = GPIO_NUM_38;  // E2A 右前
constexpr gpio_num_t ENC_B_B_GPIO = GPIO_NUM_13;  // E2B
constexpr gpio_num_t ENC_C_A_GPIO = GPIO_NUM_47;  // E3A 左前
constexpr gpio_num_t ENC_C_B_GPIO = GPIO_NUM_41;  // E3B
// 若 d 仍为 0，多半是 E4A/E4B 对调或座子无信号；先按丝印，诊断固件会报两相边沿。
constexpr gpio_num_t ENC_D_A_GPIO = GPIO_NUM_42;  // E4A 左后
constexpr gpio_num_t ENC_D_B_GPIO = GPIO_NUM_39;  // E4B
constexpr bool ENC_INVERT_A = false;
constexpr bool ENC_INVERT_B = true;
constexpr bool ENC_INVERT_C = true;   // 前进应为正
constexpr bool ENC_INVERT_D = false;
constexpr int SPEED_BALANCE_KP = 8;
constexpr int SPEED_TRIM_MAX = 20;
constexpr int SERVO_PWM_FREQUENCY_HZ = 50;
constexpr int SERVO_CENTER_PULSE_US = 1500;
constexpr int SERVO_PERIOD_US = 20000;
