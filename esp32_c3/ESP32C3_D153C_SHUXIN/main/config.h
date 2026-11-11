#pragma once
#include "driver/gpio.h"
// 七根控制线经 3.3V -> 5V 非反相缓冲器后连接D153C。
constexpr gpio_num_t MOTOR_PWMA_GPIO = GPIO_NUM_0;
constexpr gpio_num_t MOTOR_AIN1_GPIO = GPIO_NUM_1;
constexpr gpio_num_t MOTOR_AIN2_GPIO = GPIO_NUM_3;
constexpr gpio_num_t MOTOR_PWMB_GPIO = GPIO_NUM_4;
constexpr gpio_num_t MOTOR_BIN1_GPIO = GPIO_NUM_5;
constexpr gpio_num_t MOTOR_BIN2_GPIO = GPIO_NUM_6;
constexpr gpio_num_t MOTOR_STBY_GPIO = GPIO_NUM_7;
constexpr int MOTOR_PWM_FREQUENCY_HZ = 10000;
constexpr int MOTOR_DEFAULT_SPEED_PERCENT = 70;
constexpr int64_t MOTION_TIMEOUT_US = 4000000;
constexpr int64_t BRAKE_DURATION_US = 50000;
// A=左轮，B=右轮；沿用原源码镜像安装方向：B正转IN1=0、IN2=1。
constexpr bool MOTOR_INVERT_A = false;
constexpr bool MOTOR_INVERT_B = true;
constexpr int CONTROL_UART_TX = 21;
constexpr int CONTROL_UART_RX = 20;
constexpr int CONTROL_UART_BAUD = 115200;
// 颈部 MG996R：50Hz。GPIO1 已被 AIN1 占用，不能复用 S3 那套接线。
// 舵机红线 5–6V，不要接 12V。
constexpr gpio_num_t SERVO_PAN_GPIO = GPIO_NUM_10;
constexpr gpio_num_t SERVO_TILT_GPIO = GPIO_NUM_8;
