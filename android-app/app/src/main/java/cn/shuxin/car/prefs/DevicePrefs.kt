package cn.shuxin.car.prefs

import android.content.Context
import android.content.SharedPreferences
import android.os.UserManager
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class DevicePrefs(context: Context) {
    private val prefs: SharedPreferences = open(context)

    var wsUrl: String
        get() = prefs.getString("ws_url", DEFAULT_WS).orEmpty().ifBlank { DEFAULT_WS }
        set(value) { prefs.edit().putString("ws_url", value.trim()).apply() }

    /** 机器人代号，对应服务端 robot_code / device_id。 */
    var deviceCode: String
        get() = prefs.getString("device_code", "").orEmpty()
        set(value) { prefs.edit().putString("device_code", value.trim()).apply() }

    /** 用户显示名，对应服务端 user_name；轻量连接不再使用 device_secret。 */
    var userName: String
        get() = prefs.getString("user_name", "").orEmpty().ifBlank {
            prefs.getString("device_secret", "").orEmpty().takeIf { it.length in 1..16 && !it.equals("k11c", true) }.orEmpty()
        }
        set(value) { prefs.edit().putString("user_name", value.trim()).apply() }

    @Deprecated("Use userName; WS hello no longer sends device_secret")
    var deviceSecret: String
        get() = userName
        set(value) { userName = value }

    var weatherCity: String
        get() = prefs.getString("weather_city", DEFAULT_CITY).orEmpty().ifBlank { DEFAULT_CITY }
        set(value) { prefs.edit().putString("weather_city", value.trim()).apply() }

    fun memos(): List<String> {
        val raw = prefs.getString("memos", "").orEmpty()
        if (raw.isBlank()) return emptyList()
        return raw.split("\n").map { it.trim() }.filter { it.isNotEmpty() }
    }

    fun addMemo(text: String) {
        val next = (listOf(text.trim()) + memos()).distinct().take(20)
        prefs.edit().putString("memos", next.joinToString("\n")).apply()
    }

    companion object {
        const val DEFAULT_WS = "ws://127.0.0.1:8765/ws/voice"
        const val DEFAULT_DEVICE_CODE = "SX-000003"
        const val DEFAULT_USER_NAME = "小林"
        @Deprecated("Lab pin no longer used for WS auth")
        const val DEFAULT_LAB_PIN = LabSecretResolver.LAB_PIN
        const val DEFAULT_CITY = "上海"
        const val DE_PREFS = "device_creds_de"
        const val CE_FALLBACK = "device_creds_fallback"

        fun open(context: Context): SharedPreferences {
            val app = context.applicationContext
            val de = app.createDeviceProtectedStorageContext()
            val prefs = try {
                val key = MasterKey.Builder(de)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build()
                EncryptedSharedPreferences.create(
                    de,
                    "device_creds",
                    key,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
                )
            } catch (_: Exception) {
                de.getSharedPreferences(DE_PREFS, Context.MODE_PRIVATE)
            }
            migrateFromCredentialStore(app, prefs)
            return prefs
        }

        private fun migrateFromCredentialStore(app: Context, dest: SharedPreferences) {
            val um = app.getSystemService(UserManager::class.java)
            if (um?.isUserUnlocked != true) return
            if (dest.getBoolean("migrated_from_ce", false)) return
            if (dest.contains("ws_url") || dest.contains("device_code")) {
                dest.edit().putBoolean("migrated_from_ce", true).apply()
                return
            }
            val copied = runCatching {
                app.getSharedPreferences(CE_FALLBACK, Context.MODE_PRIVATE)
            }.getOrNull() ?: return
            val editor = dest.edit()
            copied.all.forEach { (key, value) ->
                when (value) {
                    is String -> editor.putString(key, value)
                    is Boolean -> editor.putBoolean(key, value)
                    is Int -> editor.putInt(key, value)
                }
            }
            editor.putBoolean("migrated_from_ce", true).apply()
        }
    }
}
