import { BleTransport } from "./ble-transport";
import { DEFAULT_PROV_SERVICE_UUID, PROV_WIFI_POLL_INTERVAL_MS, PROV_WIFI_POLL_MAX_ATTEMPTS } from "./constants";
import { Security1Session } from "./security1";
import {
  buildEncryptedApplyConfig,
  buildEncryptedGetStatus,
  buildEncryptedSetConfig,
  parseApplyConfigResponse,
  parseGetStatusResponse,
  parseSetConfigResponse,
  type WifiProvisionStatus,
} from "./wifi-config-proto";

export type { WifiProvisionStatus };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function mapWifiStatusToMessage(status: WifiProvisionStatus): string {
  switch (status) {
    case "connected":
      return "设备联网成功";
    case "connecting":
      return "设备正在连接 Wi-Fi...";
    case "disconnected":
      return "设备尚未连接 Wi-Fi";
    case "failed_auth":
      return "Wi-Fi 密码错误";
    case "failed_not_found":
      return "找不到指定的 Wi-Fi";
    case "failed":
      return "设备连接 Wi-Fi 失败";
    default:
      return "未知网络状态";
  }
}

export class EspIdfProvisionClient {
  private readonly transport: BleTransport;
  private readonly security: Security1Session;
  private sessionReady = false;

  constructor(deviceId: string, pop: string, serviceUuid = DEFAULT_PROV_SERVICE_UUID) {
    this.transport = new BleTransport(deviceId, serviceUuid);
    this.security = new Security1Session(pop);
  }

  async establishSession(): Promise<void> {
    await this.transport.discoverEndpoints();
    let request = this.security.createSessionRequest0();
    let response = await this.transport.sendRecv("prov-session", request);
    request = this.security.processSessionResponse0(response);
    response = await this.transport.sendRecv("prov-session", request);
    this.security.processSessionResponse1(response);
    this.sessionReady = true;
  }

  async provisionWifi(
    ssid: string,
    password: string,
    onStatus?: (status: WifiProvisionStatus) => void,
  ): Promise<void> {
    if (!this.sessionReady) {
      throw new Error("配网会话未建立");
    }

    let request = buildEncryptedSetConfig(this.security, ssid, password);
    let response = await this.transport.sendRecv("prov-config", request);
    const setStatus = parseSetConfigResponse(this.security.decrypt(response));
    if (setStatus !== 0) {
      throw new Error(`Wi-Fi 配置写入失败（status=${setStatus}）`);
    }

    request = buildEncryptedApplyConfig(this.security);
    response = await this.transport.sendRecv("prov-config", request);
    const applyStatus = parseApplyConfigResponse(this.security.decrypt(response));
    if (applyStatus !== 0) {
      throw new Error(`应用 Wi-Fi 配置失败（status=${applyStatus}）`);
    }

    for (let attempt = 0; attempt < PROV_WIFI_POLL_MAX_ATTEMPTS; attempt += 1) {
      await sleep(PROV_WIFI_POLL_INTERVAL_MS);
      request = buildEncryptedGetStatus(this.security);
      response = await this.transport.sendRecv("prov-config", request);
      const status = parseGetStatusResponse(this.security.decrypt(response));
      onStatus?.(status);
      if (status === "connected") {
        return;
      }
      if (status === "failed_auth" || status === "failed_not_found" || status === "failed") {
        throw new Error(mapWifiStatusToMessage(status));
      }
    }
    throw new Error("配网超时，请检查 Wi-Fi 密码与信号");
  }
}
