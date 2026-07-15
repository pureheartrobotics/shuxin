import {
  DEFAULT_ENDPOINT_SHORT_UUID,
  DEFAULT_PROV_SERVICE_UUID,
  PROV_REQUEST_TIMEOUT_MS,
  USER_DESCRIPTION_DESCRIPTOR_UUID,
} from "./constants";
import {
  arrayBufferToUint8Array,
  utf8Decode,
  uint8ArrayToArrayBuffer,
} from "./protobuf-wire";
import { bluetoothUuidMatches, deriveEndpointCharacteristicUuid } from "./bluetooth-uuid";

const SERVICE_DISCOVERY_RETRY_MS = [500, 1000, 1500];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

type UniBleHandler = (res: UniNamespace.OnBLECharacteristicValueChangeCallbackResult) => void;

function getServices(deviceId: string): Promise<UniNamespace.GetBLEDeviceServicesSuccessCallbackResult> {
  return new Promise((resolve, reject) => {
    uni.getBLEDeviceServices({
      deviceId,
      success: resolve,
      fail: (err) => reject(new Error(err.errMsg || "获取服务失败")),
    });
  });
}

function getCharacteristics(
  deviceId: string,
  serviceId: string,
): Promise<UniNamespace.GetBLEDeviceCharacteristicsSuccessCallbackResult> {
  return new Promise((resolve, reject) => {
    uni.getBLEDeviceCharacteristics({
      deviceId,
      serviceId,
      success: resolve,
      fail: (err) => reject(new Error(err.errMsg || "获取特征值失败")),
    });
  });
}

function getDescriptors(
  deviceId: string,
  serviceId: string,
  characteristicId: string,
): Promise<UniNamespace.GetBLEDeviceDescriptorsSuccessCallbackResult> {
  return new Promise((resolve, reject) => {
    uni.getBLEDeviceDescriptors({
      deviceId,
      serviceId,
      characteristicId,
      success: resolve,
      fail: (err) => reject(new Error(err.errMsg || "获取描述符失败")),
    });
  });
}

function readDescriptor(
  deviceId: string,
  serviceId: string,
  characteristicId: string,
  descriptorId: string,
): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    uni.readBLEDescriptorValue({
      deviceId,
      serviceId,
      characteristicId,
      descriptorId,
      success: (res) => resolve(res.value as ArrayBuffer),
      fail: (err) => reject(new Error(err.errMsg || "读取描述符失败")),
    });
  });
}

function supportsBleDescriptors(): boolean {
  return typeof uni.getBLEDeviceDescriptors === "function";
}

export class BleTransport {
  private readonly deviceId: string;
  private serviceUuid: string;
  private readonly endpoints: Record<string, string> = {};
  private readonly verifiedEndpoints = new Set<string>();
  private readonly properties: Record<string, UniNamespace.BLECharacteristicProperties> = {};
  private readonly log: (msg: string) => void;

  constructor(deviceId: string, serviceUuid = DEFAULT_PROV_SERVICE_UUID, log?: (msg: string) => void) {
    this.deviceId = deviceId;
    this.serviceUuid = serviceUuid.toLowerCase();
    this.log = log ?? (() => {});
  }

  getServiceUuid(): string {
    return this.serviceUuid;
  }

  hasEndpoint(endpointName: string): boolean {
    return this.verifiedEndpoints.has(endpointName);
  }

  getEndpointCharacteristicId(endpointName: string): string | null {
    return this.endpoints[endpointName] ?? null;
  }

  private registerEndpoint(name: string, characteristicId: string, source: string): void {
    this.endpoints[name] = characteristicId;
    this.verifiedEndpoints.add(name);
    this.log(`endpoint[${name}] verified (${source}) → ${characteristicId}`);
  }

  async discoverEndpoints(): Promise<void> {
    let target: UniNamespace.BluetoothService | undefined;
    let discoveredUuids: string[] = [];

    for (let attempt = 0; attempt <= SERVICE_DISCOVERY_RETRY_MS.length; attempt += 1) {
      if (attempt > 0) {
        await sleep(SERVICE_DISCOVERY_RETRY_MS[attempt - 1]);
      }
      const services = await getServices(this.deviceId);
      const list = services.services || [];
      discoveredUuids = list.map((service) => service.uuid);
      target = list.find((service) => bluetoothUuidMatches(service.uuid, this.serviceUuid));
      if (target) {
        break;
      }
    }

    if (!target) {
      const summary = discoveredUuids.length > 0 ? discoveredUuids.join(", ") : "无";
      throw new Error(`未找到 ESP-IDF 配网 BLE 服务（已发现: ${summary}）`);
    }
    this.serviceUuid = target.uuid;
    this.log(`✓ 找到配网服务: ${this.serviceUuid}`);

    const characteristics = await getCharacteristics(this.deviceId, this.serviceUuid);
    const charList = (characteristics.characteristics || []).map((c) => c.uuid);
    this.log(`特征值列表(${charList.length}): ${charList.join(" | ")}`);

    const wechatUuidMap: Record<string, string> = {};

    for (const characteristic of characteristics.characteristics || []) {
      const props = characteristic.properties || {};
      this.log(
        `特征[${characteristic.uuid.slice(4, 8)}] 属性: R=${props.read}, W=${props.write}, N=${props.notify}, I=${props.indicate}`,
      );

      for (const shortUuid of Object.values(DEFAULT_ENDPOINT_SHORT_UUID)) {
        const derived = deriveEndpointCharacteristicUuid(this.serviceUuid, shortUuid);
        if (bluetoothUuidMatches(characteristic.uuid, derived)) {
          wechatUuidMap[derived.toLowerCase()] = characteristic.uuid;
          this.properties[characteristic.uuid.toLowerCase()] = props;
        }
      }

      if (!supportsBleDescriptors()) {
        continue;
      }

      try {
        const descriptorResult = await getDescriptors(this.deviceId, this.serviceUuid, characteristic.uuid);
        const userDesc = (descriptorResult.descriptors || []).find((item) =>
          bluetoothUuidMatches(item.uuid, USER_DESCRIPTION_DESCRIPTOR_UUID),
        );
        if (!userDesc) {
          continue;
        }
        const value = await readDescriptor(
          this.deviceId,
          this.serviceUuid,
          characteristic.uuid,
          userDesc.uuid,
        );
        const endpointName = utf8Decode(arrayBufferToUint8Array(value))
          .replace(/\0/g, "")
          .trim();
        if (!endpointName || !(endpointName in DEFAULT_ENDPOINT_SHORT_UUID)) {
          continue;
        }
        if (!this.verifiedEndpoints.has(endpointName)) {
          this.registerEndpoint(endpointName, characteristic.uuid, "描述符");
          this.properties[characteristic.uuid.toLowerCase()] = props;
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        this.log(`特征[${characteristic.uuid.slice(4, 8)}] 读描述符失败: ${message}`);
      }
    }

    if (!supportsBleDescriptors()) {
      this.log("描述符 API 不可用，使用 UUID 匹配");
    }

    for (const [name, shortUuid] of Object.entries(DEFAULT_ENDPOINT_SHORT_UUID)) {
      if (this.verifiedEndpoints.has(name)) {
        continue;
      }
      const derived = deriveEndpointCharacteristicUuid(this.serviceUuid, shortUuid);
      const resolved = wechatUuidMap[derived.toLowerCase()];
      if (resolved) {
        this.registerEndpoint(name, resolved, "UUID 匹配");
      } else {
        this.log(`endpoint[${name}] missing (未在设备上发现)`);
      }
    }

    if (!this.endpoints["prov-session"] || !this.endpoints["prov-config"]) {
      throw new Error("未找到 prov-session / prov-config 端点");
    }

    // 发现特征值后延时 500ms，避开手机蓝牙栈的 Busy/GattError 竞争状态
    this.log("等待蓝牙栈稳定 (500ms)...");
    await sleep(500);
  }

  async sendRecv(endpointName: string, payload: Uint8Array): Promise<Uint8Array> {
    const characteristicId = this.endpoints[endpointName];
    if (!characteristicId) {
      throw new Error(`未知 endpoint: ${endpointName}`);
    }
    const props = this.properties[characteristicId.toLowerCase()] || {};
    const supportsNotify = Boolean(props.notify || props.indicate);
    this.log(`sendRecv(${endpointName}) → 支持通知: ${supportsNotify}`);

    return new Promise((resolve, reject) => {
      let settled = false;
      const cleanup = (handler: UniBleHandler) => {
        uni.offBLECharacteristicValueChange(handler);
      };

      const handler: UniBleHandler = (res) => {
        if (!bluetoothUuidMatches(res.characteristicId, characteristicId)) {
          return;
        }
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        cleanup(handler);
        resolve(arrayBufferToUint8Array(res.value as ArrayBuffer));
      };

      const timer = setTimeout(() => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup(handler);
        reject(new Error(`${endpointName} 响应超时`));
      }, PROV_REQUEST_TIMEOUT_MS);

      uni.onBLECharacteristicValueChange(handler);

      const performWrite = () => {
        uni.writeBLECharacteristicValue({
          deviceId: this.deviceId,
          serviceId: this.serviceUuid,
          characteristicId,
          value: uint8ArrayToArrayBuffer(payload),
          success: () => {
            if (!supportsNotify) {
              // 如果不支持 Notify/Indicate，我们写入成功后主动发起 Read，响应同样在 onBLECharacteristicValueChange 接收
              uni.readBLECharacteristicValue({
                deviceId: this.deviceId,
                serviceId: this.serviceUuid,
                characteristicId,
                fail: (err) => {
                  if (settled) return;
                  settled = true;
                  clearTimeout(timer);
                  cleanup(handler);
                  reject(new Error(`读取特征值响应失败: ${err.errMsg}`));
                }
              });
            }
          },
          fail: (err) => {
            if (settled) {
              return;
            }
            settled = true;
            clearTimeout(timer);
            cleanup(handler);
            reject(new Error(err.errMsg || "BLE 写入失败"));
          },
        });
      };

      if (supportsNotify) {
        uni.notifyBLECharacteristicValueChange({
          deviceId: this.deviceId,
          serviceId: this.serviceUuid,
          characteristicId,
          state: true,
          success: () => {
            performWrite();
          },
          fail: (err) => {
            if (settled) {
              return;
            }
            settled = true;
            clearTimeout(timer);
            cleanup(handler);
            reject(new Error(err.errMsg || "BLE 订阅失败"));
          },
        });
      } else {
        performWrite();
      }
    });
  }
}
