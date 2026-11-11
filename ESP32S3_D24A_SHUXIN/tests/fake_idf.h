#pragma once
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
inline int64_t fake_us=0;
inline int levels[49]{},duties[8]{};
#define ESP_ERROR_CHECK(expr) assert((expr)==0)
#define pdMS_TO_TICKS(ms) (ms)
enum gpio_num_t{GPIO_NUM_0,GPIO_NUM_1,GPIO_NUM_2,GPIO_NUM_3,GPIO_NUM_4,GPIO_NUM_5,GPIO_NUM_6,GPIO_NUM_7,
 GPIO_NUM_8,GPIO_NUM_9,GPIO_NUM_10,GPIO_NUM_11,GPIO_NUM_12,GPIO_NUM_13,GPIO_NUM_14,GPIO_NUM_15,
 GPIO_NUM_16,GPIO_NUM_17,GPIO_NUM_18,GPIO_NUM_19,GPIO_NUM_20,GPIO_NUM_21,
 GPIO_NUM_38=38,GPIO_NUM_39=39,GPIO_NUM_40=40,GPIO_NUM_41=41,GPIO_NUM_42=42,GPIO_NUM_46=46};
enum gpio_inttype_t{GPIO_INTR_DISABLE=0,GPIO_INTR_ANYEDGE=3};
inline int gpio_get_level(gpio_num_t){return 0;}
inline int gpio_install_isr_service(int){return 0;}
inline int gpio_isr_handler_add(gpio_num_t, void(*)(void*), void*){return 0;}
enum ledc_channel_t{LEDC_CHANNEL_0,LEDC_CHANNEL_1,LEDC_CHANNEL_2,LEDC_CHANNEL_3,LEDC_CHANNEL_4,LEDC_CHANNEL_5};
enum uart_port_t{UART_NUM_1};
constexpr int GPIO_MODE_OUTPUT=1,GPIO_MODE_INPUT=0,GPIO_PULLDOWN_ENABLE=1,GPIO_PULLDOWN_DISABLE=0,GPIO_PULLUP_ENABLE=1,GPIO_PULLUP_DISABLE=0,LEDC_LOW_SPEED_MODE=0,
 LEDC_TIMER_10_BIT=10,LEDC_TIMER_14_BIT=14,LEDC_TIMER_0=0,LEDC_TIMER_1=1,LEDC_AUTO_CLK=0,UART_DATA_8_BITS=8,
 UART_PARITY_DISABLE=0,UART_STOP_BITS_1=1,UART_HW_FLOWCTRL_DISABLE=0,
 UART_SCLK_DEFAULT=0,UART_PIN_NO_CHANGE=-1;
struct gpio_config_t{uint64_t pin_bit_mask;int mode,pull_down_en,pull_up_en,intr_type;};
enum i2c_port_t{I2C_NUM_0=0};
constexpr int I2C_CLK_SRC_DEFAULT=0,ESP_OK=0;
struct i2c_master_bus_config_t{
    int i2c_port,sda_io_num,scl_io_num,clk_source,glitch_ignore_cnt;
    struct { bool enable_internal_pullup; } flags;
};
struct i2c_master_bus_t;
using i2c_master_bus_handle_t = i2c_master_bus_t*;
inline int i2c_new_master_bus(const i2c_master_bus_config_t*, i2c_master_bus_handle_t* h){ *h=nullptr; return 0; }
inline int i2c_del_master_bus(i2c_master_bus_handle_t){ return 0; }
inline int i2c_master_probe(i2c_master_bus_handle_t, uint16_t, int){ return 1; }
struct ledc_timer_config_t{int speed_mode,duty_resolution,timer_num,freq_hz,clk_cfg;};
struct ledc_channel_config_t{int gpio_num,speed_mode;ledc_channel_t channel;int timer_sel;uint32_t duty;int hpoint;};
struct uart_config_t{int baud_rate,data_bits,parity,stop_bits,flow_ctrl,source_clk;};
struct usb_serial_jtag_driver_config_t{int tx_buffer_size,rx_buffer_size;};
inline int gpio_config(const gpio_config_t*){return 0;}
inline int gpio_set_level(gpio_num_t p,int v){levels[p]=v;return 0;}
inline int ledc_timer_config(const ledc_timer_config_t*){return 0;}
inline int ledc_channel_config(const ledc_channel_config_t*){return 0;}
inline int ledc_set_duty(int,ledc_channel_t c,uint32_t d){duties[c]=d;return 0;}
inline int ledc_update_duty(int,ledc_channel_t){return 0;}
inline int64_t esp_timer_get_time(){return fake_us;}
inline void vTaskDelay(int ms){fake_us+=ms*1000;}
inline int uart_param_config(uart_port_t,const uart_config_t*){return 0;}
inline int uart_set_pin(uart_port_t,int,int,int,int){return 0;}
inline int uart_driver_install(uart_port_t,int,int,int,void*,int){return 0;}
inline int uart_write_bytes(uart_port_t,const void*,size_t n){return static_cast<int>(n);}
inline int uart_read_bytes(uart_port_t,void*,size_t,int){return 0;}
inline int usb_serial_jtag_driver_install(const usb_serial_jtag_driver_config_t*){return 0;}
inline int usb_serial_jtag_write_bytes(const void*,size_t n,int){return static_cast<int>(n);}
inline int usb_serial_jtag_read_bytes(void*,size_t,int){return 0;}
