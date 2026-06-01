<!--
 * @Author: Haibo Huang
 * @Date: 2026-05-20 17:16:58
 * @Description: 文件用途描述
-->
# STT/TTS 本地部署 vs API 调用简要对比

## 一句话结论

如果只是做桌面小屏 Agent 聊天机器人，**优先推荐 API / 服务端部署**；  
只有在强隐私、离线使用、无网络环境下，才考虑本地部署。

---

## 核心区别

| 对比项 | 本地部署 | API / 服务端调用 |
|---|---|---|
| 运行位置 | 模型跑在机器人本机或本地服务器 | 模型跑在云端/后端服务器 |
| 硬件要求 | 高，需要较强 CPU/GPU | 设备端要求低 |
| 设备成本 | 高 | 低 |
| 延迟 | 局域网可低，低配设备会很慢 | 取决于网络和服务器 |
| 稳定性 | 受本机性能影响大 | 后端统一维护，更稳定 |
| 模型升级 | 每台设备都要更新 | 只更新服务端 |
| 并发能力 | 单设备能力有限 | 可通过服务器扩展 |
| 隐私性 | 更好，数据不出本地 | 语音/文本需要上传 |
| 离线能力 | 可以离线运行 | 依赖网络 |
| 适合阶段 | 隐私场景、离线产品、技术验证 | MVP、演示、产品早期、低成本量产 |

---

## 配置差异

### 本地部署

**CPU 本地跑 Faster-Whisper，TTS 用 API**

如果机器人本机直接跑 Faster-Whisper + CosyVoice2：


```text
最低：16GB 内存 + 8GB GPU 8核
推荐：32GB 内存 + 12GB/16GB GPU 

```

千牛云  https://buy.cloud.tencent.com/price/cvm?devPayMode=monthly&regionId=33&zoneId=330001&instanceType=SA9.MEDIUM2&imageType=linux&systemDiskType=CLOUD_BSSD&systemDiskSize=50&bandwidthType=BANDWIDTH_PREPAID&bandwidth=1

![image-20260520172614714](C:\Users\11844\AppData\Roaming\Typora\typora-user-images\image-20260520172614714.png)



api的形式 

腾讯云

https://cloud.tencent.com/document/product/1093/35686

![image-20260520174347349](C:/Users/11844/AppData/Roaming/Typora/typora-user-images/image-20260520174347349.png)
