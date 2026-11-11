#pragma once
#include "config.h"
#include "command.h"
#include "driver/ledc.h"
#include "esp_timer.h"

// 50Hz / 13bit：500–2500µs 对应 0–180°。电机占用 timer0 与 channel 0/1。
class Neck {
public:
    void Initialize() {
        ledc_timer_config_t timer{};
        timer.speed_mode = LEDC_LOW_SPEED_MODE;
        timer.duty_resolution = LEDC_TIMER_13_BIT;
        timer.timer_num = LEDC_TIMER_1;
        timer.freq_hz = 50;
        timer.clk_cfg = LEDC_AUTO_CLK;
        ESP_ERROR_CHECK(ledc_timer_config(&timer));
        Configure(kPanCh, SERVO_PAN_GPIO);
        Configure(kTiltCh, SERVO_TILT_GPIO);
        SetDeg(90, 90);
    }

    void Execute(const HeadCommand &command) {
        gesture_ = false;
        if (command.kind == HeadKind::Set) {
            SetDeg(command.pan, command.tilt);
            return;
        }
        step_ = 0;
        if (command.kind == HeadKind::Nod) LoadNod();
        else LoadShake();
        gesture_ = true;
        next_us_ = 0;
        Poll();
    }

    void Poll() {
        if (!gesture_ || esp_timer_get_time() < next_us_) return;
        if (step_ >= count_) {
            gesture_ = false;
            return;
        }
        SetDeg(frames_[step_].pan, frames_[step_].tilt);
        next_us_ = esp_timer_get_time() + frames_[step_].hold_us;
        step_++;
    }

private:
    struct Frame {
        int pan;
        int tilt;
        int64_t hold_us;
    };
    static constexpr ledc_channel_t kPanCh = LEDC_CHANNEL_2;
    static constexpr ledc_channel_t kTiltCh = LEDC_CHANNEL_3;
    static constexpr uint32_t kMaxDuty = 8191;
    Frame frames_[6]{};
    int count_ = 0;
    int step_ = 0;
    bool gesture_ = false;
    int64_t next_us_ = 0;

    void Configure(ledc_channel_t channel, gpio_num_t pin) {
        ledc_channel_config_t cfg{};
        cfg.gpio_num = pin;
        cfg.speed_mode = LEDC_LOW_SPEED_MODE;
        cfg.channel = channel;
        cfg.timer_sel = LEDC_TIMER_1;
        ESP_ERROR_CHECK(ledc_channel_config(&cfg));
    }

    static int DegToUs(int deg) {
        if (deg < 0) deg = 0;
        if (deg > 180) deg = 180;
        return 500 + deg * 2000 / 180;
    }

    void WritePulse(ledc_channel_t channel, int us) {
        if (us < 500) us = 500;
        if (us > 2500) us = 2500;
        const uint32_t duty = static_cast<uint32_t>(us) * kMaxDuty / 20000u;
        ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, channel, duty));
        ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, channel));
    }

    void SetDeg(int pan, int tilt) {
        WritePulse(kPanCh, DegToUs(pan));
        WritePulse(kTiltCh, DegToUs(tilt));
    }

    void LoadNod() {
        count_ = 5;
        frames_[0] = {90, 90, 80000};
        frames_[1] = {90, 62, 220000};
        frames_[2] = {90, 118, 220000};
        frames_[3] = {90, 62, 220000};
        frames_[4] = {90, 90, 220000};
    }

    void LoadShake() {
        count_ = 5;
        frames_[0] = {90, 90, 80000};
        frames_[1] = {52, 90, 220000};
        frames_[2] = {128, 90, 220000};
        frames_[3] = {52, 90, 220000};
        frames_[4] = {90, 90, 220000};
    }
};
