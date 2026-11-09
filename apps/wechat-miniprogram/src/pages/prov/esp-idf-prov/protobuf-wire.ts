/** 精简 protobuf wire 编解码（仅覆盖 ESP-IDF 配网所需消息） */

export function concatBytes(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

export function encodeVarint(value: number): Uint8Array {
  const bytes: number[] = [];
  let v = value >>> 0;
  while (v >= 0x80) {
    bytes.push((v & 0x7f) | 0x80);
    v >>>= 7;
  }
  bytes.push(v);
  return new Uint8Array(bytes);
}

function encodeTag(fieldNumber: number, wireType: number): Uint8Array {
  return encodeVarint((fieldNumber << 3) | wireType);
}

export function encodeVarintField(fieldNumber: number, value: number): Uint8Array {
  return concatBytes(encodeTag(fieldNumber, 0), encodeVarint(value));
}

export function encodeBytesField(fieldNumber: number, data: Uint8Array): Uint8Array {
  return concatBytes(encodeTag(fieldNumber, 2), encodeVarint(data.length), data);
}

export function encodeMessageField(fieldNumber: number, data: Uint8Array): Uint8Array {
  return encodeBytesField(fieldNumber, data);
}

export type ProtoField = {
  number: number;
  wireType: number;
  value: number | Uint8Array;
};

export function decodeFields(buffer: Uint8Array): ProtoField[] {
  const fields: ProtoField[] = [];
  let offset = 0;
  while (offset < buffer.length) {
    const tagResult = readVarint(buffer, offset);
    if (!tagResult) break;
    offset = tagResult.next;
    const tag = tagResult.value;
    const wireType = tag & 0x07;
    const fieldNumber = tag >>> 3;
    if (wireType === 0) {
      const varint = readVarint(buffer, offset);
      if (!varint) break;
      fields.push({ number: fieldNumber, wireType, value: varint.value });
      offset = varint.next;
      continue;
    }
    if (wireType === 2) {
      const lenResult = readVarint(buffer, offset);
      if (!lenResult) break;
      offset = lenResult.next;
      const end = offset + lenResult.value;
      fields.push({
        number: fieldNumber,
        wireType,
        value: buffer.slice(offset, end),
      });
      offset = end;
      continue;
    }
    break;
  }
  return fields;
}

export function readVarint(buffer: Uint8Array, offset: number): { value: number; next: number } | null {
  let result = 0;
  let shift = 0;
  let index = offset;
  while (index < buffer.length) {
    const byte = buffer[index++];
    result |= (byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) {
      return { value: result >>> 0, next: index };
    }
    shift += 7;
    if (shift > 35) {
      return null;
    }
  }
  return null;
}

export function getBytesField(fields: ProtoField[], fieldNumber: number): Uint8Array | null {
  const field = fields.find((item) => item.number === fieldNumber && item.wireType === 2);
  return field && field.value instanceof Uint8Array ? field.value : null;
}

export function getVarintField(fields: ProtoField[], fieldNumber: number): number | null {
  const field = fields.find((item) => item.number === fieldNumber && item.wireType === 0);
  return typeof field?.value === "number" ? field.value : null;
}

export function utf8Encode(text: string): Uint8Array {
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(text);
  }
  const bytes: number[] = [];
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code < 0x80) {
      bytes.push(code);
    } else if (code < 0x800) {
      bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else {
      bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    }
  }
  return new Uint8Array(bytes);
}

export function utf8Decode(buffer: Uint8Array): string {
  if (typeof TextDecoder !== "undefined") {
    return new TextDecoder().decode(buffer);
  }
  return String.fromCharCode(...buffer);
}

export function arrayBufferToUint8Array(buffer: ArrayBuffer): Uint8Array {
  return new Uint8Array(buffer);
}

export function uint8ArrayToArrayBuffer(buffer: Uint8Array): ArrayBuffer {
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength) as ArrayBuffer;
}
