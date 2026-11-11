package cn.shuxin.car.face

import java.util.concurrent.TimeUnit

object PowerOff {
    fun now(): Boolean {
        val commands = listOf(
            arrayOf("su", "0", "reboot", "-p"),
            arrayOf("su", "-c", "reboot -p"),
            arrayOf("reboot", "-p"),
        )
        for (command in commands) {
            val ok = runCatching {
                val process = Runtime.getRuntime().exec(command)
                if (!process.waitFor(4, TimeUnit.SECONDS)) {
                    process.destroy()
                    false
                } else {
                    process.exitValue() == 0
                }
            }.getOrDefault(false)
            if (ok) return true
        }
        return false
    }
}
