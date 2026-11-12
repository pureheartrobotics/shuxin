# Carrier V1.4 布局说明

- 板框：170 × 120 mm，2 层  
- 左列电源：JBAT → D1 → F1 → SW1 → JVM / JK11 / UBUCK / JP1  
- 中：P1（K11C）、系列电阻、UART/ENC/CTRL  
- 右：P2/P3 DevKit（**22.86 mm**）、舵机与 ToF  
- 电源 Netclass **Power = 1.6 mm**；B.Cu 整板 GND  
- 重建：`gen/build_board_v14.py` → `run_freerouting.py all` → `post_fix_power.py`  

DRC（KiCad 10.0.8）：**0 unconnected / 0 short / 0 clearance**；丝印与库 courtyard 警告可忽略电气。
