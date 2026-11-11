#pragma once
#include "config.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include <atomic>
#include <cstdio>

// 四轮正交。D 额外统计两相原始边沿，便于判断「无信号 / A-B 对调」。
class WheelEncoders {
public:
    void Initialize() {
        InstallLevelPin(ENC_A_B_GPIO);
        InstallLevelPin(ENC_B_B_GPIO);
        InstallLevelPin(ENC_C_B_GPIO);
        InstallEdgePin(ENC_A_A_GPIO);
        InstallEdgePin(ENC_B_A_GPIO);
        InstallEdgePin(ENC_C_A_GPIO);
        // D：两相都挂边沿，便于诊断
        InstallEdgePin(ENC_D_A_GPIO);
        InstallEdgePin(ENC_D_B_GPIO);
        ESP_ERROR_CHECK(gpio_install_isr_service(0));
        ESP_ERROR_CHECK(gpio_isr_handler_add(ENC_A_A_GPIO, IsrA, this));
        ESP_ERROR_CHECK(gpio_isr_handler_add(ENC_B_A_GPIO, IsrB, this));
        ESP_ERROR_CHECK(gpio_isr_handler_add(ENC_C_A_GPIO, IsrC, this));
        ESP_ERROR_CHECK(gpio_isr_handler_add(ENC_D_A_GPIO, IsrDa, this));
        ESP_ERROR_CHECK(gpio_isr_handler_add(ENC_D_B_GPIO, IsrDb, this));
        last_us_ = esp_timer_get_time();
        last_a_ = last_b_ = last_c_ = last_d_ = 0;
        cps_a_ = cps_b_ = cps_c_ = cps_d_ = 0;
    }

    bool Poll() {
        const int64_t now = esp_timer_get_time();
        const int64_t dt = now - last_us_;
        if (dt < 50000) return false;
        const int32_t ca = count_a_.load(std::memory_order_relaxed);
        const int32_t cb = count_b_.load(std::memory_order_relaxed);
        const int32_t cc = count_c_.load(std::memory_order_relaxed);
        const int32_t cd = count_d_.load(std::memory_order_relaxed);
        cps_a_ = static_cast<int>((ca - last_a_) * 1000000LL / dt);
        cps_b_ = static_cast<int>((cb - last_b_) * 1000000LL / dt);
        cps_c_ = static_cast<int>((cc - last_c_) * 1000000LL / dt);
        cps_d_ = static_cast<int>((cd - last_d_) * 1000000LL / dt);
        last_a_ = ca;
        last_b_ = cb;
        last_c_ = cc;
        last_d_ = cd;
        last_us_ = now;
        return true;
    }

    int32_t CountA() const { return count_a_.load(std::memory_order_relaxed); }
    int32_t CountB() const { return count_b_.load(std::memory_order_relaxed); }
    int32_t CountC() const { return count_c_.load(std::memory_order_relaxed); }
    int32_t CountD() const { return count_d_.load(std::memory_order_relaxed); }
    int CpsA() const { return cps_a_; }
    int CpsB() const { return cps_b_; }
    int CpsC() const { return cps_c_; }
    int CpsD() const { return cps_d_; }

    int CpsLeftAbs() const { return SideAvg(cps_c_, cps_d_); }
    int CpsRightAbs() const { return SideAvg(cps_b_, cps_a_); }

    void Reset() {
        count_a_.store(0, std::memory_order_relaxed);
        count_b_.store(0, std::memory_order_relaxed);
        count_c_.store(0, std::memory_order_relaxed);
        count_d_.store(0, std::memory_order_relaxed);
        edge_da_.store(0, std::memory_order_relaxed);
        edge_db_.store(0, std::memory_order_relaxed);
        last_a_ = last_b_ = last_c_ = last_d_ = 0;
        cps_a_ = cps_b_ = cps_c_ = cps_d_ = 0;
        last_us_ = esp_timer_get_time();
    }

    int Format(char *buf, size_t n, int trim_percent = 0) const {
        return snprintf(buf, n,
            "ENC a=%ld/%d b=%ld/%d c=%ld/%d d=%ld/%d trim=%d "
            "dA_e=%ld dB_e=%ld dLv=%d%d\r\n",
            static_cast<long>(CountA()), CpsA(),
            static_cast<long>(CountB()), CpsB(),
            static_cast<long>(CountC()), CpsC(),
            static_cast<long>(CountD()), CpsD(),
            trim_percent,
            static_cast<long>(edge_da_.load(std::memory_order_relaxed)),
            static_cast<long>(edge_db_.load(std::memory_order_relaxed)),
            gpio_get_level(ENC_D_A_GPIO),
            gpio_get_level(ENC_D_B_GPIO));
    }

private:
    std::atomic<int32_t> count_a_{0}, count_b_{0}, count_c_{0}, count_d_{0};
    std::atomic<int32_t> edge_da_{0}, edge_db_{0};
    int32_t last_a_ = 0, last_b_ = 0, last_c_ = 0, last_d_ = 0;
    int cps_a_ = 0, cps_b_ = 0, cps_c_ = 0, cps_d_ = 0;
    int64_t last_us_ = 0;

    static int Abs(int v) { return v < 0 ? -v : v; }

    static int SideAvg(int x, int y) {
        const int ax = Abs(x), ay = Abs(y);
        if (ay < 20 && ax > 50) return ax;
        if (ax < 20 && ay > 50) return ay;
        return (ax + ay) / 2;
    }

    static void InstallLevelPin(gpio_num_t pin) {
        gpio_config_t io{};
        io.pin_bit_mask = 1ULL << pin;
        io.mode = GPIO_MODE_INPUT;
        io.pull_up_en = GPIO_PULLUP_ENABLE;
        io.pull_down_en = GPIO_PULLDOWN_DISABLE;
        io.intr_type = GPIO_INTR_DISABLE;
        ESP_ERROR_CHECK(gpio_config(&io));
    }

    static void InstallEdgePin(gpio_num_t pin) {
        gpio_config_t io{};
        io.pin_bit_mask = 1ULL << pin;
        io.mode = GPIO_MODE_INPUT;
        io.pull_up_en = GPIO_PULLUP_ENABLE;
        io.pull_down_en = GPIO_PULLDOWN_DISABLE;
        io.intr_type = GPIO_INTR_ANYEDGE;
        ESP_ERROR_CHECK(gpio_config(&io));
    }

    static void QuadStep(std::atomic<int32_t> &count, gpio_num_t pin_a, gpio_num_t pin_b, bool invert) {
        const int a = gpio_get_level(pin_a);
        const int b = gpio_get_level(pin_b);
        int step = (a == b) ? 1 : -1;
        if (invert) step = -step;
        count.fetch_add(step, std::memory_order_relaxed);
    }

    static void IsrA(void *arg) {
        auto *self = static_cast<WheelEncoders *>(arg);
        QuadStep(self->count_a_, ENC_A_A_GPIO, ENC_A_B_GPIO, ENC_INVERT_A);
    }
    static void IsrB(void *arg) {
        auto *self = static_cast<WheelEncoders *>(arg);
        QuadStep(self->count_b_, ENC_B_A_GPIO, ENC_B_B_GPIO, ENC_INVERT_B);
    }
    static void IsrC(void *arg) {
        auto *self = static_cast<WheelEncoders *>(arg);
        QuadStep(self->count_c_, ENC_C_A_GPIO, ENC_C_B_GPIO, ENC_INVERT_C);
    }
    static void IsrDa(void *arg) {
        auto *self = static_cast<WheelEncoders *>(arg);
        self->edge_da_.fetch_add(1, std::memory_order_relaxed);
        QuadStep(self->count_d_, ENC_D_A_GPIO, ENC_D_B_GPIO, ENC_INVERT_D);
    }
    static void IsrDb(void *arg) {
        auto *self = static_cast<WheelEncoders *>(arg);
        self->edge_db_.fetch_add(1, std::memory_order_relaxed);
    }
};
