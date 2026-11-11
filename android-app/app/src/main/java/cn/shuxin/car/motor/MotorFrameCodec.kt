package cn.shuxin.car.motor

data class MotorFrame(
    val type: Int,
    val sequence: Int,
    val payload: ByteArray,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is MotorFrame) return false
        return type == other.type && sequence == other.sequence && payload.contentEquals(other.payload)
    }

    override fun hashCode(): Int {
        var result = type
        result = 31 * result + sequence
        result = 31 * result + payload.contentHashCode()
        return result
    }
}

object MotorFrameCodec {
    const val HEADER0 = 0xAA.toByte()
    const val HEADER1 = 0x55.toByte()
    const val VERSION = 0x01.toByte()
    const val MAX_PAYLOAD = 32

    const val TYPE_HEARTBEAT = 0x01
    const val TYPE_SET_MOTOR = 0x10
    const val TYPE_STOP = 0x11
    const val TYPE_QUERY_STATUS = 0x20
    const val TYPE_ACK = 0x80
    const val TYPE_STATUS = 0x81
    const val TYPE_FAULT = 0xE0

    fun encode(type: Int, sequence: Int, payload: ByteArray = byteArrayOf()): ByteArray {
        require(payload.size <= MAX_PAYLOAD) { "payload too long" }
        val body = ByteArray(4 + payload.size)
        body[0] = VERSION
        body[1] = type.toByte()
        body[2] = payload.size.toByte()
        body[3] = (sequence and 0xFF).toByte()
        if (payload.isNotEmpty()) {
            payload.copyInto(body, 4)
        }
        val crc = Crc16CcittFalse.compute(body)
        val frame = ByteArray(body.size + 4)
        frame[0] = HEADER0
        frame[1] = HEADER1
        body.copyInto(frame, 2)
        frame[frame.size - 2] = (crc shr 8).toByte()
        frame[frame.size - 1] = (crc and 0xFF).toByte()
        return frame
    }

    fun setMotorPayload(left: Int, right: Int, durationMs: Int): ByteArray {
        val duration = durationMs.coerceIn(0, 4000)
        return byteArrayOf(
            left.coerceIn(-100, 100).toByte(),
            right.coerceIn(-100, 100).toByte(),
            (duration and 0xFF).toByte(),
            ((duration shr 8) and 0xFF).toByte(),
        )
    }

    fun decodeOne(buffer: ByteArray, offset: Int = 0, length: Int = buffer.size - offset): Pair<MotorFrame, Int>? {
        val end = offset + length
        var i = offset
        while (i + 8 <= end) {
            if (buffer[i] != HEADER0 || buffer[i + 1] != HEADER1) {
                i++
                continue
            }
            if (buffer[i + 2] != VERSION) {
                i++
                continue
            }
            val payloadLen = buffer[i + 4].toInt() and 0xFF
            if (payloadLen > MAX_PAYLOAD) {
                i++
                continue
            }
            val frameLen = 6 + payloadLen + 2
            if (i + frameLen > end) {
                return null
            }
            val body = buffer.copyOfRange(i + 2, i + 6 + payloadLen)
            val expected = Crc16CcittFalse.compute(body)
            val actual = ((buffer[i + frameLen - 2].toInt() and 0xFF) shl 8) or
                (buffer[i + frameLen - 1].toInt() and 0xFF)
            if (expected != actual) {
                i++
                continue
            }
            val frame = MotorFrame(
                type = buffer[i + 3].toInt() and 0xFF,
                sequence = buffer[i + 5].toInt() and 0xFF,
                payload = if (payloadLen == 0) byteArrayOf() else buffer.copyOfRange(i + 6, i + 6 + payloadLen),
            )
            return frame to (i + frameLen - offset)
        }
        return null
    }
}

object WheelMap {
    fun cloudSpeedToWheel(speed: Double): Int {
        return (speed.coerceIn(0.0, 1.0) * 100.0).toInt().coerceIn(0, 100)
    }

    fun wheelsFor(action: String, speed: Double): Pair<Int, Int> {
        val s = cloudSpeedToWheel(speed)
        return when (action) {
            "go_forward", "self.chassis.go_forward", "self.chassis.forward" -> s to s
            "go_back", "self.chassis.go_back", "self.chassis.go_backward", "self.chassis.backward" -> -s to -s
            "turn_left", "self.chassis.turn_left", "self.chassis.left" -> -s to s
            "turn_right", "self.chassis.turn_right", "self.chassis.right" -> s to -s
            "spin", "self.chassis.spin" -> s to -s
            else -> 0 to 0
        }
    }
}
