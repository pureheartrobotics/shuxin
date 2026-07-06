import {
  DEFAULT_ENDPOINT_SUFFIX,
  DEFAULT_PROV_SERVICE_UUID,
  PROV_REQUEST_TIMEOUT_MS,
  USER_DESCRIPTION_DESCRIPTOR_UUID,
} from "./constants";
import {
  arrayBufferToUint8Array,
  utf8Decode,
  uint8ArrayToArrayBuffer,
} from "./protobuf-wire";

function normalizeUuid(uuid: string): string {
  return String(uuid || "").toLowerCase().replace(/-/g, "");
}

export function deriveCharacteristicUuid(serviceUuid: string, shortHex: string): string {
  const normalized = serviceUuid.toLowerCase();
  const prefix = normalized.slice(0, 4);
  const mask = parseInt(normalized.slice(4, 8), 16);
  const merged = (parseInt(shortHex, 16) & mask).toString(16).padStart(4, "0");
  return `${prefix}${merged}${normalized.slice(8)}`;
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

export class BleTransport {
  private readonly deviceId: string;
  private serviceUuid: string;
  private readonly endpoints: Record<string, string> = {};

  constructor(deviceId: string, serviceUuid = DEFAULT_PROV_SERVICE_UUID) {
    this.deviceId = deviceId;
    this.serviceUuid = serviceUuid.toLowerCase();
  }

  getServiceUuid(): string {
    return this.serviceUuid;
  }

  async discoverEndpoints(): Promise<void> {
    const services = await getServices(this.deviceId);
    const target = (services.services || []).find(
      (service) => normalizeUuid(service.uuid) === normalizeUuid(this.serviceUuid),
    );
    if (!target) {
      throw new Error("未找到 ESP-IDF 配网 BLE 服务");
    }
    this.serviceUuid = target.uuid;

    const characteristics = await getCharacteristics(this.deviceId, this.serviceUuid);
    for (const characteristic of characteristics.characteristics || []) {
      try {
        const descriptors = await getDescriptors(this.deviceId, this.serviceUuid, characteristic.uuid);
        const userDescriptor = (descriptors.descriptors || []).find(
          (item) => normalizeUuid(item.uuid) === normalizeUuid(USER_DESCRIPTION_DESCRIPTOR_UUID),
        );
        if (!userDescriptor) {
          continue;
        }
        const value = await readDescriptor(
          this.deviceId,
          this.serviceUuid,
          characteristic.uuid,
          userDescriptor.uuid,
        );
        const endpointName = utf8Decode(arrayBufferToUint8Array(value)).replace(/\0/g, "").trim();
        if (endpointName) {
          this.endpoints[endpointName] = characteristic.uuid;
        }
      } catch {
        // 部分平台读描述符失败时走 fallback
      }
    }

    for (const [name, suffix] of Object.entries(DEFAULT_ENDPOINT_SUFFIX)) {
      if (!this.endpoints[name]) {
        this.endpoints[name] = deriveCharacteristicUuid(this.serviceUuid, suffix);
      }
    }

    if (!this.endpoints["prov-session"] || !this.endpoints["prov-config"]) {
      throw new Error("未找到 prov-session / prov-config 端点");
    }
  }

  async sendRecv(endpointName: string, payload: Uint8Array): Promise<Uint8Array> {
    const characteristicId = this.endpoints[endpointName];
    if (!characteristicId) {
      throw new Error(`未知 endpoint: ${endpointName}`);
    }

    return new Promise((resolve, reject) => {
      let settled = false;
      const cleanup = (handler: UniBleHandler) => {
        uni.offBLECharacteristicValueChange(handler);
      };

      const handler: UniBleHandler = (res) => {
        if (normalizeUuid(res.characteristicId) !== normalizeUuid(characteristicId)) {
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
      uni.notifyBLECharacteristicValueChange({
        deviceId: this.deviceId,
        serviceId: this.serviceUuid,
        characteristicId,
        state: true,
        success: () => {
          uni.writeBLECharacteristicValue({
            deviceId: this.deviceId,
            serviceId: this.serviceUuid,
            characteristicId,
            value: uint8ArrayToArrayBuffer(payload),
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
    });
  }
}
