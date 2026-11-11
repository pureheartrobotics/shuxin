package cn.shuxin.car.motor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class MotorFrameCodecTest {
    @Test
    fun heartbeatSeq0() {
        val encoded = MotorFrameCodec.encode(MotorFrameCodec.TYPE_HEARTBEAT, 0)
        assertEquals("aa5501010000c544", encoded.toHex())
        val decoded = MotorFrameCodec.decodeOne(encoded)
        assertNotNull(decoded)
        assertEquals(MotorFrameCodec.TYPE_HEARTBEAT, decoded!!.first.type)
        assertEquals(0, decoded.first.sequence)
        assertEquals(encoded.size, decoded.second)
    }

    @Test
    fun stopSeq1() {
        val encoded = MotorFrameCodec.encode(MotorFrameCodec.TYPE_STOP, 1)
        assertEquals("aa55011100019606", encoded.toHex())
    }

    @Test
    fun setMotorForward() {
        val payload = MotorFrameCodec.setMotorPayload(55, 55, 1500)
        val encoded = MotorFrameCodec.encode(MotorFrameCodec.TYPE_SET_MOTOR, 2, payload)
        assertEquals("aa55011004023737dc053eaa", encoded.toHex())
    }

    @Test
    fun setMotorLeftNegative() {
        val payload = MotorFrameCodec.setMotorPayload(-40, 40, 800)
        val encoded = MotorFrameCodec.encode(MotorFrameCodec.TYPE_SET_MOTOR, 3, payload)
        assertEquals("aa5501100403d82820039dc7", encoded.toHex())
    }

    @Test
    fun wheelMap() {
        assertEquals(55 to 55, WheelMap.wheelsFor("self.chassis.go_forward", 0.55))
        assertEquals(-85 to -85, WheelMap.wheelsFor("self.chassis.go_back", 0.85))
        assertEquals(-35 to 35, WheelMap.wheelsFor("self.chassis.turn_left", 0.35))
        assertEquals(55 to -55, WheelMap.wheelsFor("self.chassis.turn_right", 0.55))
        assertEquals(0 to 0, WheelMap.wheelsFor("self.chassis.stop", 0.55))
    }

    @Test
    fun chassisSerialMatchesC3Firmware() {
        assertEquals("F 55", ChassisSerial.encode(55, 55))
        assertEquals("B 85", ChassisSerial.encode(-85, -85))
        assertEquals("L 35", ChassisSerial.encode(-35, 35))
        assertEquals("R 55", ChassisSerial.encode(55, -55))
        assertEquals("S", ChassisSerial.encode(0, 0))
        assertEquals("S", ChassisSerial.encode(12, 0))
    }

    private fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it.toInt() and 0xFF) }
}
