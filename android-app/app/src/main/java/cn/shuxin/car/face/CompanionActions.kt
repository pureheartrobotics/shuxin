package cn.shuxin.car.face

import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import cn.shuxin.car.camera.CameraCapture
import cn.shuxin.car.camera.PhotoAlbum
import cn.shuxin.car.motor.NeckController
import cn.shuxin.car.prefs.DevicePrefs
import java.util.concurrent.Executors

class CompanionActions(
    private val prefs: DevicePrefs,
    private val face: FaceController,
    private val weather: WeatherClient = WeatherClient(),
    private val camera: CameraCapture? = null,
    private val sendVision: (ByteArray) -> Unit = {},
    private val powerOff: () -> Boolean = { PowerOff.now() },
    private val neck: NeckController? = null,
    private val album: PhotoAlbum? = null,
) {
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var lastText = ""
    private var lastAt = 0L
    @Volatile private var wantLookCard = false

    fun handleUtterance(text: String): Boolean {
        val compact = text.replace("\\s+".toRegex(), "")
        val now = System.currentTimeMillis()
        if (compact.isEmpty() || (compact == lastText && now - lastAt < 2500)) return false
        val intent = CompanionIntents.parse(text) ?: return false
        if (CompanionIntents.isHermesBody(intent)) return false
        lastText = compact
        lastAt = now
        return dispatch(intent)
    }

    fun startTimer(seconds: Int) {
        face.showProcess(timerProcess(seconds))
        face.startTimer(seconds)
    }

    fun saveMemo(text: String) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        prefs.addMemo(clean)
        face.showProcess("记下了")
        face.showMemo(clean)
    }

    fun recallMemos() {
        face.showProcess("翻备忘")
        face.showMemos(prefs.memos())
    }

    fun shutdown() {
        face.showProcess("关机")
        io.execute {
            val ok = runCatching { powerOff() }.getOrDefault(false)
            if (!ok) {
                main.post { face.showPowerOffFailed() }
            }
        }
    }

    fun lookQuiet() {
        look(showCard = false)
    }

    fun look(showCard: Boolean = true) {
        if (showCard) {
            wantLookCard = true
            face.showProcess("在看")
        }
        val capture = camera
        if (capture == null) {
            if (showCard) face.showLookFailed()
            return
        }
        capture.capture { jpeg ->
            val card = wantLookCard
            wantLookCard = false
            if (jpeg == null || jpeg.isEmpty()) {
                if (card) face.showLookFailed()
                return@capture
            }
            if (card) {
                val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
                if (bitmap != null) face.showLook(bitmap) else face.showLookFailed()
            }
            sendVision(jpeg)
        }
    }

    fun lookAround() {
        wantLookCard = true
        face.showProcess("环顾")
        val head = neck
        if (head == null) {
            look()
            return
        }
        head.lookAround(
            onPose = { name ->
                face.showProcess(
                    when (name) {
                        "left" -> "左边"
                        "right" -> "右边"
                        "up" -> "上面"
                        "down" -> "下面"
                        else -> "环顾"
                    },
                )
            },
            onDone = { look() },
        )
    }

    fun photo() {
        wantLookCard = false
        face.showProcess("拍照")
        val capture = camera
        val store = album
        if (capture == null) {
            face.showLookFailed()
            return
        }
        capture.capture { jpeg ->
            if (jpeg == null || jpeg.isEmpty()) {
                face.showLookFailed()
                return@capture
            }
            store?.save(jpeg)
            val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
            if (bitmap != null) face.showLook(bitmap, "拍好了") else face.showLookFailed()
        }
    }

    fun showAlbum() {
        face.showProcess("相册")
        val files = album?.latest(8).orEmpty()
        if (files.isEmpty()) {
            face.showAlbumEmpty()
            return
        }
        val bitmaps = files.mapNotNull { BitmapFactory.decodeFile(it.absolutePath) }
        if (bitmaps.isEmpty()) face.showAlbumEmpty() else face.showAlbum(bitmaps)
    }

    fun nod() {
        face.showProcess("点头")
        neck?.nod()
    }

    fun shake() {
        face.showProcess("摇头")
        neck?.shake()
    }

    fun turnHead(pan: Int, tilt: Int) {
        face.showProcess("转头")
        neck?.pose(pan.coerceIn(0, 180), tilt.coerceIn(0, 180))
    }

    fun showWeather(city: String? = null, temperature: Int? = null, summary: String? = null) {
        val place = city?.ifBlank { null } ?: prefs.weatherCity
        if (temperature != null && !summary.isNullOrBlank()) {
            prefs.weatherCity = place
            face.showProcess("查天气")
            face.showWeather(place, temperature, summary)
            return
        }
        face.showProcess("查天气")
        io.execute {
            try {
                val snap = weather.fetch(place)
                main.post {
                    prefs.weatherCity = snap.city
                    face.showWeather(snap.city, snap.temperature, snap.summary)
                }
            } catch (_: Exception) {
                main.post { face.showWeatherFailed() }
            }
        }
    }

    private fun dispatch(intent: CompanionIntent): Boolean {
        when (intent) {
            is CompanionIntent.Weather -> showWeather(intent.city)
            is CompanionIntent.Timer -> startTimer(intent.seconds)
            is CompanionIntent.Memo -> saveMemo(intent.text)
            CompanionIntent.RecallMemos -> recallMemos()
            CompanionIntent.Shutdown -> shutdown()
            CompanionIntent.Look -> look()
            CompanionIntent.LookAround -> lookAround()
            CompanionIntent.Photo -> photo()
            CompanionIntent.Album -> showAlbum()
            CompanionIntent.Nod -> nod()
            CompanionIntent.Shake -> shake()
        }
        return true
    }

    companion object {
        fun timerProcess(seconds: Int): String {
            return when {
                seconds % 3600 == 0 -> "定了 ${seconds / 3600} 小时"
                seconds % 60 == 0 -> "定了 ${seconds / 60} 分钟"
                else -> "定了 ${seconds} 秒"
            }
        }
    }
}
