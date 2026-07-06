import {
  concatBytes,
  decodeFields,
  encodeBytesField,
  encodeVarintField,
  getBytesField,
  getVarintField,
  utf8Encode,
} from "./protobuf-wire";

const TYPE_CMD_GET_STATUS = 0;
const TYPE_RESP_GET_STATUS = 1;
const TYPE_CMD_SET_CONFIG = 2;
const TYPE_RESP_SET_CONFIG = 3;
const TYPE_CMD_APPLY_CONFIG = 4;
const TYPE_RESP_APPLY_CONFIG = 5;

export type WifiProvisionStatus =
  | "connected"
  | "connecting"
  | "disconnected"
  | "failed_auth"
  | "failed_not_found"
  | "failed"
  | "unknown";

export function buildEncryptedSetConfig(
  cipher: { encrypt: (data: Uint8Array) => Uint8Array },
  ssid: string,
  passphrase: string,
): Uint8Array {
  const inner = concatBytes(
    encodeVarintField(1, TYPE_CMD_SET_CONFIG),
    encodeBytesField(
      12,
      concatBytes(encodeBytesField(1, utf8Encode(ssid)), encodeBytesField(2, utf8Encode(passphrase))),
    ),
  );
  return cipher.encrypt(inner);
}

export function buildEncryptedApplyConfig(cipher: { encrypt: (data: Uint8Array) => Uint8Array }): Uint8Array {
  const inner = concatBytes(encodeVarintField(1, TYPE_CMD_APPLY_CONFIG), encodeBytesField(14, new Uint8Array(0)));
  return cipher.encrypt(inner);
}

export function buildEncryptedGetStatus(cipher: { encrypt: (data: Uint8Array) => Uint8Array }): Uint8Array {
  const inner = concatBytes(encodeVarintField(1, TYPE_CMD_GET_STATUS), encodeBytesField(10, new Uint8Array(0)));
  return cipher.encrypt(inner);
}

export function parseSetConfigResponse(decrypted: Uint8Array): number {
  const fields = decodeFields(decrypted);
  const msgType = getVarintField(fields, 1);
  if (msgType !== TYPE_RESP_SET_CONFIG) {
    throw new Error(`SetConfig 响应类型错误: ${msgType}`);
  }
  const resp = getBytesField(fields, 13);
  if (!resp) {
    throw new Error("缺少 SetConfig 响应体");
  }
  const status = getVarintField(decodeFields(resp), 1);
  return status ?? -1;
}

export function parseApplyConfigResponse(decrypted: Uint8Array): number {
  const fields = decodeFields(decrypted);
  const msgType = getVarintField(fields, 1);
  if (msgType !== TYPE_RESP_APPLY_CONFIG) {
    throw new Error(`ApplyConfig 响应类型错误: ${msgType}`);
  }
  const resp = getBytesField(fields, 15);
  if (!resp) {
    throw new Error("缺少 ApplyConfig 响应体");
  }
  const status = getVarintField(decodeFields(resp), 1);
  return status ?? -1;
}

export function parseGetStatusResponse(decrypted: Uint8Array): WifiProvisionStatus {
  const fields = decodeFields(decrypted);
  const msgType = getVarintField(fields, 1);
  if (msgType !== TYPE_RESP_GET_STATUS) {
    throw new Error(`GetStatus 响应类型错误: ${msgType}`);
  }
  const resp = getBytesField(fields, 11);
  if (!resp) {
    throw new Error("缺少 GetStatus 响应体");
  }
  const respFields = decodeFields(resp);
  const staState = getVarintField(respFields, 2);
  if (staState === 0) {
    return "connected";
  }
  if (staState === 1) {
    return "connecting";
  }
  if (staState === 2) {
    return "disconnected";
  }
  if (staState === 3) {
    const failReason = getVarintField(respFields, 10);
    if (failReason === 0) {
      return "failed_auth";
    }
    if (failReason === 1) {
      return "failed_not_found";
    }
    return "failed";
  }
  return "unknown";
}
