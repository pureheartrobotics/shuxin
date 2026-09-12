import { generateKeyPair, sharedKey } from "curve25519-js";
import sha256 from "js-sha256";
import aesjs from "aes-js";

import { randomBytes32 } from "./random-bytes";
import { buildSessionCmd0, buildSessionCmd1, parseSessionResp0, parseSessionResp1DeviceVerify, popToBytes } from "./session-proto";

function xorBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) {
    out[i] = a[i] ^ b[i];
  }
  return out;
}

function popHash(pop: Uint8Array): Uint8Array {
  return new Uint8Array(sha256.array(pop));
}

export class Security1Session {
  private readonly pop: Uint8Array;
  private clientPrivateKey: Uint8Array | null = null;
  private clientPublicKey: Uint8Array | null = null;
  private ctr: aesjs.ModeOfOperation.ctr | null = null;

  constructor(pop: string) {
    this.pop = popToBytes(pop);
  }

  createSessionRequest0(): Uint8Array {
    const keyPair = generateKeyPair(randomBytes32());
    this.clientPrivateKey = keyPair.private;
    this.clientPublicKey = keyPair.public;
    return buildSessionCmd0(this.clientPublicKey);
  }

  processSessionResponse0(response: Uint8Array): Uint8Array {
    if (!this.clientPrivateKey || !this.clientPublicKey) {
      throw new Error("Security1 未初始化客户端密钥");
    }
    const { devicePublicKey, deviceRandom } = parseSessionResp0(response);
    let shared = sharedKey(this.clientPrivateKey, devicePublicKey);
    if (this.pop.length > 0) {
      shared = xorBytes(shared, popHash(this.pop));
    }
    this.ctr = new aesjs.ModeOfOperation.ctr(shared, new aesjs.Counter(deviceRandom));
    const clientVerify = this.ctr.encrypt(devicePublicKey);
    return buildSessionCmd1(clientVerify);
  }

  processSessionResponse1(response: Uint8Array): void {
    if (!this.clientPublicKey || !this.ctr) {
      throw new Error("Security1 会话未建立");
    }
    const deviceVerify = parseSessionResp1DeviceVerify(response);
    const decrypted = this.ctr.encrypt(deviceVerify);
    if (!this.bytesEqual(decrypted, this.clientPublicKey)) {
      throw new Error("设备 PoP 校验失败，请确认选择了正确的设备");
    }
  }

  encrypt(data: Uint8Array): Uint8Array {
    if (!this.ctr) {
      throw new Error("Security1 会话未建立");
    }
    return this.ctr.encrypt(data);
  }

  decrypt(data: Uint8Array): Uint8Array {
    return this.encrypt(data);
  }

  private bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return false;
    }
    return true;
  }
}
