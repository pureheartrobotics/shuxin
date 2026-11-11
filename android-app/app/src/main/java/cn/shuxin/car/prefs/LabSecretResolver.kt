package cn.shuxin.car.prefs

object LabSecretResolver {
    const val LAB_PIN = "k11c"

    fun resolve(deviceCode: String, typedSecret: String, table: Map<String, String>): String {
        val typed = typedSecret.trim()
        val code = deviceCode.trim()
        if (typed.equals(LAB_PIN, ignoreCase = true)) {
            val mapped = table[code]
            if (!mapped.isNullOrBlank()) return mapped
        }
        return typed
    }
}
