# shuxin 互连载板 Carrier V1.5（JST XH 2.50）

普通 FR4 互连板：K11C / S3 DevKit 排针 + **JST XH 2.50 mm** 线束。Rev **F**，板框 **170×120 mm**。

- 对 V1.4 复审必做项：`docs/REVIEW_V15_RESPONSE.md`
- 连接器：`docs/CONNECTORS.md`
- Gerber：**仅** `out/carrier_v1_gerbers.zip`（旧 `cam/` 已删除）

## 本版相对 V1.4 的硬修复

1. 电源铺铜按网重建，VBAT/GND 不相交  
2. D1 → **SR20100**（20 A 级）  
3. courtyard 冲突清零  
4. JBAT → **XT60**；BOM 与 MKDS 一致  
5. **P2-1/2 NC**（消除 3V3 双源）  
6. 文档 / 顶视图 / 废止 `REVIEW_XH254` 旧文  

## 重建

```bash
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" hardware/carrier_v1/gen/build_board_v14.py
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" hardware/carrier_v1/gen/run_freerouting.py all
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" hardware/carrier_v1/gen/post_fix_power.py
```

## 不做

- 不画 SoC 核心板  
- 不接 K11C DEBUG UART（25/27）  
- 完整原理图符号仍待补（以 PCB + `docs/nets.csv` 为准）  
