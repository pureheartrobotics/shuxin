# Carrier V1.5 布局

- 170×120 mm，2 层，Rev F  
- 左：XT60 → SR20100 → FUSE/SW → VM 区  
- 中：P1、电阻、UART/ENC/CTRL  
- 右：DevKit 22.86、舵机/ToF、C_SERVO 在 x≈160  
- 铺铜：B.Cu GND；F.Cu VBAT / VBAT_F / VM / V_SERVO（互不重叠）  

重建：`build_board_v14.py` → `run_freerouting.py all` → `post_fix_power.py`
