package cn.shuxin.car.motor

import kotlin.math.abs

/** Maps wheel speeds to the ESP32-C3 ASCII protocol (newline-terminated). */
object ChassisSerial {
    fun encode(left: Int, right: Int): String {
        val l = left.coerceIn(-100, 100)
        val r = right.coerceIn(-100, 100)
        val pct = maxOf(abs(l), abs(r))
        if (pct == 0) return "S"
        return when {
            l > 0 && r > 0 -> "F $pct"
            l < 0 && r < 0 -> "B $pct"
            l < 0 && r > 0 -> "L $pct"
            l > 0 && r < 0 -> "R $pct"
            else -> "S"
        }
    }
}
