#include "wifi_board.h"
#include "application.h"
#include "codecs/no_audio_codec.h"
#include "config.h"
#include "mcp_server.h"
#include "display/lcd_display.h"
#include "backlight.h"

#include <algorithm>
#include <mutex>
#include <driver/gpio.h>
#include <driver/i2c_master.h>
#include <driver/ledc.h>
#include <driver/spi_master.h>
#include <esp_check.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_st77916.h>
#include <esp_lcd_touch_gt911.h>
#include <esp_lvgl_port.h>
#include <esp_log.h>
#include <esp_timer.h>

#define TAG "Jc4827w543Tb6612"

// The ST77916 component supplies the generic QSPI panel transport used by the
// NV3041A. These commands are the NV3041A sequence shipped with this board.
static const st77916_lcd_init_cmd_t kNv3041aInitCommands[] = {
    {0xFF, (uint8_t[]){0xA5}, 1, 0}, {0x36, (uint8_t[]){0xC0}, 1, 0},
    {0x3A, (uint8_t[]){0x01}, 1, 0}, {0x41, (uint8_t[]){0x03}, 1, 0},
    {0x44, (uint8_t[]){0x15}, 1, 0}, {0x45, (uint8_t[]){0x15}, 1, 0},
    {0x7D, (uint8_t[]){0x03}, 1, 0}, {0xC1, (uint8_t[]){0xAB}, 1, 0},
    {0xC2, (uint8_t[]){0x17}, 1, 0}, {0xC3, (uint8_t[]){0x10}, 1, 0},
    {0xC6, (uint8_t[]){0x3A}, 1, 0}, {0xC7, (uint8_t[]){0x25}, 1, 0},
    {0xC8, (uint8_t[]){0x11}, 1, 0}, {0x7A, (uint8_t[]){0x49}, 1, 0},
    {0x6F, (uint8_t[]){0x2F}, 1, 0}, {0x78, (uint8_t[]){0x4B}, 1, 0},
    {0xC9, (uint8_t[]){0x00}, 1, 0}, {0x67, (uint8_t[]){0x33}, 1, 0},
    {0x51, (uint8_t[]){0x4B}, 1, 0}, {0x52, (uint8_t[]){0x7C}, 1, 0},
    {0x53, (uint8_t[]){0x1C}, 1, 0}, {0x54, (uint8_t[]){0x77}, 1, 0},
    {0x46, (uint8_t[]){0x0A}, 1, 0}, {0x47, (uint8_t[]){0x2A}, 1, 0},
    {0x48, (uint8_t[]){0x0A}, 1, 0}, {0x49, (uint8_t[]){0x1A}, 1, 0},
    {0x56, (uint8_t[]){0x43}, 1, 0}, {0x57, (uint8_t[]){0x42}, 1, 0},
    {0x58, (uint8_t[]){0x3C}, 1, 0}, {0x59, (uint8_t[]){0x64}, 1, 0},
    {0x5A, (uint8_t[]){0x41}, 1, 0}, {0x5B, (uint8_t[]){0x3C}, 1, 0},
    {0x5C, (uint8_t[]){0x02}, 1, 0}, {0x5D, (uint8_t[]){0x3C}, 1, 0},
    {0x5E, (uint8_t[]){0x1F}, 1, 0}, {0x60, (uint8_t[]){0x80}, 1, 0},
    {0x61, (uint8_t[]){0x3F}, 1, 0}, {0x62, (uint8_t[]){0x21}, 1, 0},
    {0x63, (uint8_t[]){0x07}, 1, 0}, {0x64, (uint8_t[]){0xE0}, 1, 0},
    {0x65, (uint8_t[]){0x01}, 1, 0}, {0xCA, (uint8_t[]){0x20}, 1, 0},
    {0xCB, (uint8_t[]){0x52}, 1, 0}, {0xCC, (uint8_t[]){0x10}, 1, 0},
    {0xCD, (uint8_t[]){0x42}, 1, 0}, {0xD0, (uint8_t[]){0x20}, 1, 0},
    {0xD1, (uint8_t[]){0x52}, 1, 0}, {0xD2, (uint8_t[]){0x10}, 1, 0},
    {0xD3, (uint8_t[]){0x42}, 1, 0}, {0xD4, (uint8_t[]){0x0A}, 1, 0},
    {0xD5, (uint8_t[]){0x32}, 1, 0},
    {0x80, (uint8_t[]){0x04}, 1, 0}, {0xA0, (uint8_t[]){0x00}, 1, 0},
    {0x81, (uint8_t[]){0x07}, 1, 0}, {0xA1, (uint8_t[]){0x05}, 1, 0},
    {0x82, (uint8_t[]){0x06}, 1, 0}, {0xA2, (uint8_t[]){0x04}, 1, 0},
    {0x86, (uint8_t[]){0x2C}, 1, 0}, {0xA6, (uint8_t[]){0x2A}, 1, 0},
    {0x87, (uint8_t[]){0x46}, 1, 0}, {0xA7, (uint8_t[]){0x44}, 1, 0},
    {0x83, (uint8_t[]){0x39}, 1, 0}, {0xA3, (uint8_t[]){0x39}, 1, 0},
    {0x84, (uint8_t[]){0x3A}, 1, 0}, {0xA4, (uint8_t[]){0x3A}, 1, 0},
    {0x85, (uint8_t[]){0x3F}, 1, 0}, {0xA5, (uint8_t[]){0x3F}, 1, 0},
    {0x88, (uint8_t[]){0x08}, 1, 0}, {0xA8, (uint8_t[]){0x08}, 1, 0},
    {0x89, (uint8_t[]){0x0F}, 1, 0}, {0xA9, (uint8_t[]){0x0F}, 1, 0},
    {0x8A, (uint8_t[]){0x17}, 1, 0}, {0xAA, (uint8_t[]){0x17}, 1, 0},
    {0x8B, (uint8_t[]){0x10}, 1, 0}, {0xAB, (uint8_t[]){0x10}, 1, 0},
    {0x8C, (uint8_t[]){0x16}, 1, 0}, {0xAC, (uint8_t[]){0x16}, 1, 0},
    {0x8D, (uint8_t[]){0x14}, 1, 0}, {0xAD, (uint8_t[]){0x14}, 1, 0},
    {0x8E, (uint8_t[]){0x11}, 1, 0}, {0xAE, (uint8_t[]){0x11}, 1, 0},
    {0x8F, (uint8_t[]){0x14}, 1, 0}, {0xAF, (uint8_t[]){0x14}, 1, 0},
    {0x90, (uint8_t[]){0x06}, 1, 0}, {0xB0, (uint8_t[]){0x06}, 1, 0},
    {0x91, (uint8_t[]){0x0F}, 1, 0}, {0xB1, (uint8_t[]){0x0F}, 1, 0},
    {0x92, (uint8_t[]){0x16}, 1, 0}, {0xB2, (uint8_t[]){0x16}, 1, 0},
    {0xFF, (uint8_t[]){0x00}, 1, 0},
    {0x11, (uint8_t[]){0x00}, 1, 120},
    {0x29, (uint8_t[]){0x00}, 1, 100},
};

#include "uart_chassis.h"

class Jc4827w543Tb6612Board : public WifiBoard {
public:
    Jc4827w543Tb6612Board() {
        InitializeLcdDisplay();
        InitializeTouch();
        InitializeTools();
    }

    AudioCodec* GetAudioCodec() override {
        static NoAudioCodecSimplex audio_codec(
            AUDIO_INPUT_SAMPLE_RATE,
            AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_SPK_GPIO_BCLK,
            AUDIO_I2S_SPK_GPIO_LRCK,
            AUDIO_I2S_SPK_GPIO_DOUT,
            AUDIO_I2S_MIC_GPIO_SCK,
            AUDIO_I2S_MIC_GPIO_WS,
            AUDIO_I2S_MIC_GPIO_DIN);
        return &audio_codec;
    }

    Display* GetDisplay() override {
        return display_;
    }

    Backlight* GetBacklight() override {
        return backlight_;
    }

private:
    Tb6612Chassis chassis_;
    LcdDisplay* display_ = nullptr;
    PwmBacklight* backlight_ = nullptr;
    i2c_master_bus_handle_t touch_i2c_bus_ = nullptr;

    void InitializeLcdDisplay() {
        const spi_bus_config_t bus_config = {
            .data0_io_num = DISPLAY_QSPI_D0,
            .data1_io_num = DISPLAY_QSPI_D1,
            .sclk_io_num = DISPLAY_QSPI_SCLK,
            .data2_io_num = DISPLAY_QSPI_D2,
            .data3_io_num = DISPLAY_QSPI_D3,
            .max_transfer_sz = DISPLAY_WIDTH * 40 * sizeof(uint16_t),
        };
        ESP_ERROR_CHECK(spi_bus_initialize(DISPLAY_QSPI_HOST, &bus_config, SPI_DMA_CH_AUTO));

        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_handle_t panel = nullptr;
        esp_lcd_panel_io_spi_config_t io_config =
            ST77916_PANEL_IO_QSPI_CONFIG(DISPLAY_QSPI_CS, nullptr, nullptr);
        io_config.pclk_hz = 32 * 1000 * 1000;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(
            static_cast<esp_lcd_spi_bus_handle_t>(DISPLAY_QSPI_HOST),
            &io_config, &panel_io));

        st77916_vendor_config_t vendor_config = {
            .init_cmds = kNv3041aInitCommands,
            .init_cmds_size = sizeof(kNv3041aInitCommands) / sizeof(kNv3041aInitCommands[0]),
            .flags = {.use_qspi_interface = 1},
        };
        const esp_lcd_panel_dev_config_t panel_config = {
            .reset_gpio_num = GPIO_NUM_NC,
            .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
            .bits_per_pixel = 16,
            .vendor_config = &vendor_config,
        };
        ESP_ERROR_CHECK(esp_lcd_new_panel_st77916(panel_io, &panel_config, &panel));
        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
        ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));

        display_ = new SpiLcdDisplay(panel_io, panel,
            DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y,
            DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
        backlight_ = new PwmBacklight(DISPLAY_BACKLIGHT_PIN, DISPLAY_BACKLIGHT_OUTPUT_INVERT);
        backlight_->RestoreBrightness();
        ESP_LOGI(TAG, "NV3041A QSPI display initialized");
    }

    void InitializeTouch() {
        const i2c_master_bus_config_t bus_config = {
            .i2c_port = I2C_NUM_0,
            .sda_io_num = TOUCH_I2C_SDA_GPIO,
            .scl_io_num = TOUCH_I2C_SCL_GPIO,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .intr_priority = 0,
            .trans_queue_depth = 0,
            .flags = {.enable_internal_pullup = 1},
        };
        esp_err_t err = i2c_new_master_bus(&bus_config, &touch_i2c_bus_);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to create GT911 I2C bus: %s", esp_err_to_name(err));
            return;
        }

        esp_lcd_touch_io_gt911_config_t gt911_config = {
            .dev_addr = ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS,
        };
        const esp_lcd_touch_config_t touch_config = {
            .x_max = DISPLAY_WIDTH,
            .y_max = DISPLAY_HEIGHT,
            .rst_gpio_num = TOUCH_RST_GPIO,
            .int_gpio_num = TOUCH_INT_GPIO,
            .levels = {.reset = 0, .interrupt = 0},
            .flags = {.swap_xy = 0, .mirror_x = 0, .mirror_y = 0},
            .driver_data = &gt911_config,
        };
        esp_lcd_panel_io_handle_t touch_io = nullptr;
        esp_lcd_panel_io_i2c_config_t io_config = ESP_LCD_TOUCH_IO_I2C_GT911_CONFIG();
        io_config.scl_speed_hz = 400 * 1000;
        err = esp_lcd_new_panel_io_i2c(touch_i2c_bus_, &io_config, &touch_io);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to create GT911 panel IO: %s", esp_err_to_name(err));
            return;
        }

        esp_lcd_touch_handle_t touch = nullptr;
        err = esp_lcd_touch_new_i2c_gt911(touch_io, &touch_config, &touch);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "GT911 unavailable; continuing without touch: %s", esp_err_to_name(err));
            esp_lcd_panel_io_del(touch_io);
            return;
        }
        const lvgl_port_touch_cfg_t lvgl_touch_config = {
            .disp = lv_display_get_default(),
            .handle = touch,
        };
        lvgl_port_add_touch(&lvgl_touch_config);

        display_->SetShuxinTouchCallback([]() {
            Application::GetInstance().HandleButtonChat();
        });
        ESP_LOGI(TAG, "GT911 touch panel initialized");
    }

    void InitializeTools() {
        auto& mcp_server = McpServer::GetInstance();

        mcp_server.AddTool("self.chassis.go_forward", "让小车以固定速度前进，单次最长4秒，发送下一条方向命令可续期。", PropertyList(),
            [this](const PropertyList&) -> ReturnValue {
                chassis_.Forward(MOTOR_DEFAULT_SPEED_PERCENT);
                return chassis_.GetResult("go_forward");
            });
        mcp_server.AddTool("self.chassis.go_back", "让小车以固定速度后退，单次最长4秒，发送下一条方向命令可续期。", PropertyList(),
            [this](const PropertyList&) -> ReturnValue {
                chassis_.Backward(MOTOR_DEFAULT_SPEED_PERCENT);
                return chassis_.GetResult("go_back");
            });
        mcp_server.AddTool("self.chassis.turn_left", "让小车以固定速度原地左转，单次最长4秒，发送下一条方向命令可续期。", PropertyList(),
            [this](const PropertyList&) -> ReturnValue {
                chassis_.TurnLeft(MOTOR_DEFAULT_SPEED_PERCENT);
                return chassis_.GetResult("turn_left");
            });
        mcp_server.AddTool("self.chassis.turn_right", "让小车以固定速度原地右转，单次最长4秒，发送下一条方向命令可续期。", PropertyList(),
            [this](const PropertyList&) -> ReturnValue {
                chassis_.TurnRight(MOTOR_DEFAULT_SPEED_PERCENT);
                return chassis_.GetResult("turn_right");
            });
        mcp_server.AddTool("self.chassis.stop", "立即停止小车并让 TB6612 进入待机；用于停止、停车、别动等指令。", PropertyList(),
            [this](const PropertyList&) -> ReturnValue {
                chassis_.Stop();
                return chassis_.GetResult("stop");
            });
    }

public:
    void EmergencyStop() override {
        chassis_.Stop();
    }
};

DECLARE_BOARD(Jc4827w543Tb6612Board);
