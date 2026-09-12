import { BleTransport } from "./ble-transport";
import {
  DEFAULT_PROV_SERVICE_UUID,
  PROV_WIFI_FIRST_POLL_DELAY_MS,
  PROV_WIFI_POLL_INTERVAL_MS,
  PROV_WIFI_POLL_MAX_ATTEMPTS,
  PROV_WIFI_TERMINAL_FAILURE_THRESHOLD,
} from "./constants";
import { Security1Session } from "./security1";
import {
  buildEncryptedApplyConfig,
  buildEncryptedGetStatus,
  buildEncryptedSetConfig,
  parseApplyConfigResponse,
  isTerminalWifiProvisionFailure,
  parseGetStatusResponse,
  parseSetConfigResponse,
  type WifiProvisionStatus,
} from "./wifi-config-proto";
import {
  buildEncryptedScanResult,
  buildEncryptedScanStart,
  buildEncryptedScanStatus,
  parseScanResultResponse,
  parseScanStartResponse,
  parseScanStatusResponse,
  type WifiScanEntry,
} from "./wifi-scan-proto";
import { formatBlePayloadLog, looksLikeProtoVerJson } from "./wifi-scan-debug";

export type { WifiProvisionStatus, WifiScanEntry };

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
  private readonly log: (msg: string) => void;
  private sessionReady = false;

  constructor(deviceId: string, pop: string, serviceUuid = DEFAULT_PROV_SERVICE_UUID, log?: (msg: string) => void) {
    this.log = log ?? (() => {});
    this.transport = new BleTransport(deviceId, serviceUuid, this.log);
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

  supportsWifiScan(): boolean {
    return this.transport.hasEndpoint("prov-scan");
  }

  private assertNonEmptyBleResponse(response: Uint8Array, step: string): void {
    if (!response || response.length === 0) {
      throw new Error(`${step} 收到空 BLE 响应`);
    }
    if (looksLikeProtoVerJson(response)) {
      throw new Error("扫描请求发到了 proto-ver 端点（收到 JSON），请检查 endpoint 映射");
    }
  }

  async scanNearbyWifi(maxResults = 16): Promise<WifiScanEntry[]> {
    if (!this.sessionReady) {
      throw new Error("配网会话未建立");
    }
    if (!this.supportsWifiScan()) {
      throw new Error("设备不支持 Wi-Fi 扫描，请手动输入网络名称");
    }

    const scanEndpoint = this.transport.getEndpointCharacteristicId("prov-scan");
    this.log(`Wi-Fi 扫描开始 prov-scan=${scanEndpoint ?? "unknown"} verified=${this.supportsWifiScan()}`);

    let request = buildEncryptedScanStart(this.security);
    let response = await this.transport.sendRecv("prov-scan", request);
    this.assertNonEmptyBleResponse(response, "ScanStart");
    const scanStartDecrypted = this.security.decrypt(response);
    this.log(formatBlePayloadLog("ScanStart", response, scanStartDecrypted));
    parseScanStartResponse(scanStartDecrypted);

    let resultCount = 0;
    for (let attempt = 0; attempt < 15; attempt += 1) {
      request = buildEncryptedScanStatus(this.security);
      response = await this.transport.sendRecv("prov-scan", request);
      this.assertNonEmptyBleResponse(response, `ScanStatus#${attempt}`);
      const scanStatusDecrypted = this.security.decrypt(response);
      const status = parseScanStatusResponse(scanStatusDecrypted);
      resultCount = status.resultCount;
      this.log(
        `ScanStatus attempt=${attempt} finished=${status.scanFinished} resultCount=${status.resultCount} ${formatBlePayloadLog(
          "ScanStatus",
          response,
          scanStatusDecrypted,
        )}`,
      );
      if (status.scanFinished) {
        break;
      }
      await sleep(500);
    }

    if (resultCount <= 0) {
      this.log("Wi-Fi 扫描完成，未发现可用网络");
      return [];
    }

    request = buildEncryptedScanResult(this.security, 0, Math.min(maxResults, resultCount));
    response = await this.transport.sendRecv("prov-scan", request);
    this.assertNonEmptyBleResponse(response, "ScanResult");
    const scanResultDecrypted = this.security.decrypt(response);
    this.log(formatBlePayloadLog("ScanResult", response, scanResultDecrypted));
    const entries = parseScanResultResponse(scanResultDecrypted);
    const deduped = new Map<string, WifiScanEntry>();
    for (const entry of entries) {
      const existing = deduped.get(entry.ssid);
      if (!existing || entry.rssi > existing.rssi) {
        deduped.set(entry.ssid, entry);
      }
    }
    const sorted = Array.from(deduped.values()).sort((a, b) => b.rssi - a.rssi);
    const preview = sorted
      .slice(0, 3)
      .map((entry) => `${entry.ssid}(${entry.rssi})`)
      .join(", ");
    this.log(`Wi-Fi 扫描结果 entries=${sorted.length}${preview ? ` top=${preview}` : ""}`);
    return sorted;
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

    let terminalFailureStreak = 0;
    for (let attempt = 0; attempt < PROV_WIFI_POLL_MAX_ATTEMPTS; attempt += 1) {
      const pollDelay = attempt === 0 ? PROV_WIFI_FIRST_POLL_DELAY_MS : PROV_WIFI_POLL_INTERVAL_MS;
      await sleep(pollDelay);
      request = buildEncryptedGetStatus(this.security);
      response = await this.transport.sendRecv("prov-config", request);
      const status = parseGetStatusResponse(this.security.decrypt(response));
      onStatus?.(status);
      if (status === "connected") {
        return;
      }
      if (isTerminalWifiProvisionFailure(status)) {
        terminalFailureStreak += 1;
        if (terminalFailureStreak >= PROV_WIFI_TERMINAL_FAILURE_THRESHOLD) {
          throw new Error(mapWifiStatusToMessage(status));
        }
        this.log(
          `GetStatus 终态失败 (${terminalFailureStreak}/${PROV_WIFI_TERMINAL_FAILURE_THRESHOLD})，继续轮询…`,
        );
        continue;
      }
      terminalFailureStreak = 0;
    }
    throw new Error("配网超时，请检查 Wi-Fi 密码与信号");
  }
}
