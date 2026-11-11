package cn.shuxin.car.face

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class WeatherSnap(
    val city: String,
    val temperature: Int,
    val summary: String,
)

class WeatherClient(
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(6, TimeUnit.SECONDS)
        .build(),
) {
    fun fetch(city: String): WeatherSnap {
        val geo = get(
            "https://geocoding-api.open-meteo.com/v1/search?name=${city.encode()}&count=1&language=zh",
        )
        val place = geo.optJSONArray("results")?.optJSONObject(0)
            ?: throw IllegalStateException("找不到城市")
        val name = place.optString("name", city).ifBlank { city }
        val lat = place.getDouble("latitude")
        val lon = place.getDouble("longitude")
        val wx = get(
            "https://api.open-meteo.com/v1/forecast?latitude=$lat&longitude=$lon" +
                "&current=temperature_2m,weather_code&timezone=auto",
        )
        val current = wx.optJSONObject("current") ?: throw IllegalStateException("没有天气")
        val temp = current.optDouble("temperature_2m").toInt()
        val summary = wmo(current.optInt("weather_code"))
        return WeatherSnap(name, temp, summary)
    }

    private fun get(url: String): JSONObject {
        http.newCall(Request.Builder().url(url).get().build()).execute().use { response ->
            if (!response.isSuccessful) throw IllegalStateException("天气请求失败")
            return JSONObject(response.body?.string().orEmpty().ifBlank { "{}" })
        }
    }

    private fun String.encode(): String = java.net.URLEncoder.encode(this, "UTF-8")

    companion object {
        fun wmo(code: Int): String {
            return when (code) {
                0 -> "晴"
                in 1..3 -> "多云"
                45, 48 -> "有雾"
                in 51..67 -> "有雨"
                in 71..77 -> "有雪"
                in 80..82 -> "阵雨"
                in 95..99 -> "雷雨"
                else -> "阴"
            }
        }
    }
}
