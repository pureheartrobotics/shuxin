import {
  concatBytes,
  decodeFields,
  encodeBytesField,
  encodeMessageField,
  encodeVarintField,
  getBytesField,
  getVarintField,
  utf8Encode,
} from "./protobuf-wire";

const SEC_SCHEME1 = 1;
const SEC1_SESSION_COMMAND0 = 0;
const SEC1_SESSION_COMMAND1 = 2;

export function buildSessionCmd0(clientPublicKey: Uint8Array): Uint8Array {
  const sessionCmd0 = encodeBytesField(1, clientPublicKey);
  const sec1Payload = concatBytes(encodeMessageField(20, sessionCmd0));
  return concatBytes(encodeVarintField(2, SEC_SCHEME1), encodeMessageField(11, sec1Payload));
}

export function buildSessionCmd1(clientVerifyData: Uint8Array): Uint8Array {
  const sessionCmd1 = encodeBytesField(2, clientVerifyData);
  const sec1Payload = concatBytes(
    encodeVarintField(1, SEC1_SESSION_COMMAND1),
    encodeMessageField(22, sessionCmd1),
  );
  return concatBytes(encodeVarintField(2, SEC_SCHEME1), encodeMessageField(11, sec1Payload));
}

export type SessionResp0 = {
  devicePublicKey: Uint8Array;
  deviceRandom: Uint8Array;
};

export function parseSessionResp0(buffer: Uint8Array): SessionResp0 {
  const root = decodeFields(buffer);
  const sec1 = getBytesField(root, 11);
  if (!sec1) {
    throw new Error("缺少 sec1 响应");
  }
  const sec1Fields = decodeFields(sec1);
  const sr0 = getBytesField(sec1Fields, 21);
  if (!sr0) {
    throw new Error("缺少 SessionResp0");
  }
  const sr0Fields = decodeFields(sr0);
  const devicePublicKey = getBytesField(sr0Fields, 2);
  const deviceRandom = getBytesField(sr0Fields, 3);
  if (!devicePublicKey || !deviceRandom) {
    throw new Error("SessionResp0 字段不完整");
  }
  return { devicePublicKey, deviceRandom };
}

import { getBytesField, decodeFields } from "./protobuf-wire";

export function parseSessionResp1DeviceVerify(buffer: Uint8Array): Uint8Array {
  const root = decodeFields(buffer);
  const sec1 = getBytesField(root, 11);
  if (!sec1) {
    throw new Error("缺少 sec1 响应");
  }
  const sec1Fields = decodeFields(sec1);
  const sr1 = getBytesField(sec1Fields, 23);
  if (!sr1) {
    throw new Error("缺少 SessionResp1");
  }
  const sr1Fields = decodeFields(sr1);
  const deviceVerify = getBytesField(sr1Fields, 3);
  if (!deviceVerify) {
    throw new Error("缺少 device_verify_data");
  }
  return deviceVerify;
}

export function popToBytes(pop: string): Uint8Array {
  return utf8Encode(pop);
}
