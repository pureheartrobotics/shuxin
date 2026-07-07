/**
 * ESP-IDF v5.x wifi_prov_scheme_ble 默认 Service UUID（scheme_ble.c new_config）。
 * 旧版 ESP-IDF v4 / 显式 set_service_uuid(FFFF) 才使用 0000FFFF-...
 */
export const DEFAULT_PROV_SERVICE_UUID = "1775244d-6b43-439b-877c-060f2d9bed07";

/** 舒心设备统一使用的 ESP-IDF Security1 Proof of Possession。 */
export const PROVISION_POP = "shuxin";

/** protocomm BLE endpoint 16-bit UUID（与 ESP-IDF wifi_prov manager.c 一致） */
export const DEFAULT_ENDPOINT_SHORT_UUID: Record<string, number> = {
  "prov-scan": 0xff50,
  "prov-session": 0xff51,
  "prov-config": 0xff52,
  "proto-ver": 0xff53,
};

export const USER_DESCRIPTION_DESCRIPTOR_UUID = "00002901-0000-1000-8000-00805f9b34fb";

export const PROV_REQUEST_TIMEOUT_MS = 15000;
export const PROV_WIFI_POLL_INTERVAL_MS = 2000;
export const PROV_WIFI_POLL_MAX_ATTEMPTS = 30;
