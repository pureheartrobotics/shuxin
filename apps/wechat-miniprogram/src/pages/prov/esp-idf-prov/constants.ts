/** ESP-IDF wifi_prov_scheme_ble 默认 Service UUID（小写比较） */
export const DEFAULT_PROV_SERVICE_UUID = "0000ffff-0000-1000-8000-00805f9b34fb";

/** protocomm BLE endpoint 短 UUID（与 esp_prov transport_ble 一致） */
export const DEFAULT_ENDPOINT_SUFFIX: Record<string, string> = {
  "prov-session": "ff51",
  "prov-config": "ff52",
  "prov-scan": "ff53",
  "proto-ver": "ff54",
};

export const USER_DESCRIPTION_DESCRIPTOR_UUID = "00002901-0000-1000-8000-00805f9b34fb";

export const PROV_REQUEST_TIMEOUT_MS = 15000;
export const PROV_WIFI_POLL_INTERVAL_MS = 2000;
export const PROV_WIFI_POLL_MAX_ATTEMPTS = 30;
