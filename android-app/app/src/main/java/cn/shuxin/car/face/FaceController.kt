package cn.shuxin.car.face

import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.Window
import android.widget.ImageView
import android.widget.TextView

class FaceController(
    private val window: Window,
    private val waveform: WaveformView,
    private val faceCharacter: CharacterFaceView,
    private val wakeHint: TextView,
    private val sleepHint: TextView,
    private val caption: TextView,
    private val resultCard: View,
    private val resultKicker: TextView,
    private val resultTitle: TextView,
    private val resultDetail: TextView,
    private val resultImage: ImageView,
    private val startListen: () -> Unit,
    private val cancelTurn: () -> Unit,
    private val isReady: () -> Boolean,
    private val isLabOpen: () -> Boolean,
    private val connectNow: () -> Unit,
    private val onTimerFired: () -> Unit,
) {
    enum class State { SLEEP, LISTENING, THINKING, SPEAKING }

    var state: State = State.SLEEP
        private set

    var timerRunning: Boolean = false
        private set

    private val handler = Handler(Looper.getMainLooper())
    private val sleepRunnable = Runnable { sleep() }
    private val tickRunnable = Runnable { onTimerTick() }
    private var pendingWake = false
    private var heardSpeech = false
    private var timerRemaining = 0
    private var albumBitmaps: List<Bitmap> = emptyList()
    private var albumIndex = 0

    fun sleep(force: Boolean = false) {
        if (isLabOpen()) return
        if (timerRunning && !force) return
        if (force) {
            timerRunning = false
            handler.removeCallbacks(tickRunnable)
        }
        handler.removeCallbacks(sleepRunnable)
        if (state == State.LISTENING) {
            cancelTurn()
        }
        state = State.SLEEP
        pendingWake = false
        heardSpeech = false
        waveform.flatten()
        waveform.mode = WaveformView.Mode.SLEEP
        caption.animate().cancel()
        caption.alpha = 0f
        caption.text = ""
        hideCard()
        hideSleepHint()
        showWakeHint("轻触唤醒")
        setCharacterAwake(false)
        faceCharacter.expression = CharacterFaceView.Expression.SLEEP
        setBrightness(SLEEP_BRIGHTNESS)
    }

    fun attach() {
        state = State.SLEEP
        pendingWake = false
        heardSpeech = false
        waveform.flatten()
        waveform.mode = WaveformView.Mode.SLEEP
        caption.alpha = 0f
        caption.text = ""
        hideCard()
        hideSleepHint()
        showWakeHint("轻触唤醒")
        setCharacterAwake(false)
        faceCharacter.expression = CharacterFaceView.Expression.SLEEP
        setBrightness(SLEEP_BRIGHTNESS)
    }

    fun wake() {
        if (isLabOpen()) return
        pendingWake = true
        setCharacterAwake(true)
        faceCharacter.expression = CharacterFaceView.Expression.IDLE
        setBrightness(WAKE_BRIGHTNESS)
        caption.alpha = 1f
        if (!isReady()) {
            handler.removeCallbacks(sleepRunnable)
            state = State.THINKING
            faceCharacter.expression = CharacterFaceView.Expression.THINK
            showCaption("在连…")
            showWakeHint("轻触重连")
            showSleepHint()
            waveform.mode = WaveformView.Mode.IDLE
            connectNow()
            return
        }
        enterListening()
    }

    fun onReady() {
        if (state == State.SLEEP && !pendingWake) return
        enterListening()
    }

    fun onDisconnected() {
        handler.removeCallbacks(sleepRunnable)
        if (state == State.SLEEP && !pendingWake) return
        state = State.THINKING
        waveform.mode = WaveformView.Mode.IDLE
        faceCharacter.expression = CharacterFaceView.Expression.THINK
        showCaption("断了，轻触重连")
        showWakeHint("轻触重连")
        showSleepHint()
        armSleep()
    }

    fun onSpeechStarted() {
        if (state != State.LISTENING) return
        heardSpeech = true
        handler.removeCallbacks(sleepRunnable)
        waveform.mode = WaveformView.Mode.LISTEN
        faceCharacter.expression = CharacterFaceView.Expression.LISTEN
        showCaption("在听")
    }

    fun onListenIgnored() {
        if (isLabOpen() || state == State.SLEEP) return
        if (state == State.LISTENING) {
            heardSpeech = false
            waveform.mode = WaveformView.Mode.IDLE
            caption.animate().cancel()
            caption.alpha = 0f
            caption.text = ""
            return
        }
        if (state == State.THINKING) enterListening()
    }

    fun onListenEnded() {
        if (isLabOpen() || state != State.LISTENING) return
        handler.removeCallbacks(sleepRunnable)
        if (!heardSpeech) {
            state = State.THINKING
            waveform.mode = WaveformView.Mode.THINK
            faceCharacter.expression = CharacterFaceView.Expression.THINK
            handler.postDelayed(sleepRunnable, 12_000)
            return
        }
        state = State.THINKING
        waveform.mode = WaveformView.Mode.THINK
        faceCharacter.expression = CharacterFaceView.Expression.THINK
        if (caption.text.isNullOrBlank()) showCaption("…")
        handler.postDelayed(sleepRunnable, 25_000)
    }

    fun onStt(text: String) {
        if (state != State.LISTENING && state != State.THINKING) return
        val clean = text.trim()
        if (clean.isEmpty() || clean == "—" || clean == "…" || FillerSpeech.isFiller(clean)) return
        showCaption(clean)
        if (state == State.THINKING) {
            faceCharacter.expression = CharacterFaceView.fromText(clean, CharacterFaceView.Expression.THINK)
        }
    }

    fun onReply(text: String) {
        if (isLabOpen() || state == State.SLEEP) return
        val clean = text.trim()
        if (clean.isEmpty() || clean == "—") return
        showCaption(clean)
        faceCharacter.expression = CharacterFaceView.fromText(clean, CharacterFaceView.Expression.SPEAK)
    }

    fun onSpeaking() {
        if (state == State.SLEEP) return
        handler.removeCallbacks(sleepRunnable)
        state = State.SPEAKING
        waveform.mode = WaveformView.Mode.SPEAK
        if (faceCharacter.expression == CharacterFaceView.Expression.THINK ||
            faceCharacter.expression == CharacterFaceView.Expression.LISTEN ||
            faceCharacter.expression == CharacterFaceView.Expression.IDLE
        ) {
            faceCharacter.expression = CharacterFaceView.Expression.SPEAK
        }
    }

    fun onPlaybackIdle() {
        if (isLabOpen()) return
        if (state != State.SPEAKING && state != State.THINKING) return
        enterListening()
    }

    fun onWaveform(samples: FloatArray, playback: Boolean) {
        if (state == State.SLEEP) return
        if (playback && state != State.SPEAKING) return
        if (!playback && state != State.LISTENING) return
        waveform.push(samples)
    }

    fun onError(text: String) {
        if (state == State.SLEEP && !pendingWake) return
        if ("没听清" in text || "再说一次" in text) {
            onListenIgnored()
            return
        }
        handler.removeCallbacks(sleepRunnable)
        state = State.THINKING
        waveform.mode = WaveformView.Mode.IDLE
        showCaption(text)
        showWakeHint("轻触重连")
        showSleepHint()
        armSleep()
    }

    /** Face-only hint; does not start listening. */
    fun showNotice(text: String) {
        if (isLabOpen()) return
        pendingWake = false
        handler.removeCallbacks(sleepRunnable)
        state = State.THINKING
        waveform.mode = WaveformView.Mode.IDLE
        caption.animate().cancel()
        showCaption(text)
        setBrightness(WAKE_BRIGHTNESS)
        armSleep()
    }

    fun showProcess(text: String) {
        if (state == State.SLEEP) wake()
        handler.removeCallbacks(sleepRunnable)
        showCaption(text)
        if (state == State.LISTENING || state == State.SLEEP) {
            state = State.THINKING
            waveform.mode = WaveformView.Mode.THINK
        }
    }

    fun showWeather(city: String, temperature: Int, summary: String) {
        keepAwakeForResult()
        showCard("天气", "$temperature°", "$city · $summary")
        armSleep()
    }

    fun showMemo(text: String) {
        keepAwakeForResult()
        showCard("记下了", text, "")
        armSleep()
    }

    fun showMemos(items: List<String>) {
        keepAwakeForResult()
        val body = if (items.isEmpty()) "还没记过" else items.take(3).joinToString("\n")
        showCard("备忘", body, "")
        armSleep()
    }

    fun startTimer(seconds: Int) {
        keepAwakeForResult()
        handler.removeCallbacks(tickRunnable)
        timerRemaining = seconds.coerceIn(5, 7200)
        timerRunning = true
        renderTimer()
        handler.postDelayed(tickRunnable, 1000)
    }

    fun showWeatherFailed() {
        keepAwakeForResult()
        showCard("天气", "暂时查不到", "过一会再问")
        armSleep()
    }

    fun showLook(bitmap: Bitmap, kicker: String = "眼前") {
        albumBitmaps = emptyList()
        resultImage.setOnClickListener(null)
        keepAwakeForResult()
        resultImage.setImageBitmap(bitmap)
        resultImage.visibility = View.VISIBLE
        resultTitle.visibility = View.GONE
        resultDetail.visibility = View.GONE
        resultKicker.text = kicker
        resultCard.visibility = View.VISIBLE
        resultCard.alpha = 1f
        setBrightness(WAKE_BRIGHTNESS)
        armSleep()
    }

    fun showAlbum(bitmaps: List<Bitmap>) {
        if (bitmaps.isEmpty()) {
            showAlbumEmpty()
            return
        }
        albumBitmaps = bitmaps
        albumIndex = 0
        resultImage.setOnClickListener {
            if (albumBitmaps.isEmpty()) return@setOnClickListener
            albumIndex = (albumIndex + 1) % albumBitmaps.size
            renderAlbum()
            armSleep()
        }
        renderAlbum()
    }

    fun showAlbumEmpty() {
        albumBitmaps = emptyList()
        resultImage.setOnClickListener(null)
        keepAwakeForResult()
        showCard("相册", "还没有照片", "说拍照就会存下来")
        armSleep()
    }

    fun showLookFailed() {
        keepAwakeForResult()
        resultImage.visibility = View.GONE
        resultTitle.visibility = View.VISIBLE
        showCard("眼前", "没拍到", "看一下排线")
        armSleep()
    }

    fun showPowerOffFailed() {
        keepAwakeForResult()
        showCard("关机", "请按电源键", "板上那颗 POWER")
        armSleep()
    }

    private fun keepAwakeForResult() {
        if (state == State.SLEEP) {
            pendingWake = true
            setBrightness(WAKE_BRIGHTNESS)
            waveform.mode = WaveformView.Mode.THINK
            state = State.THINKING
        }
        handler.removeCallbacks(sleepRunnable)
    }

    private fun onTimerTick() {
        if (!timerRunning) return
        timerRemaining -= 1
        if (timerRemaining <= 0) {
            timerRunning = false
            showCard("时间到了", "到点了", "")
            setBrightness(WAKE_BRIGHTNESS)
            waveform.mode = WaveformView.Mode.IDLE
            onTimerFired()
            armSleep()
            return
        }
        renderTimer()
        handler.postDelayed(tickRunnable, 1000)
    }

    private fun renderTimer() {
        val minutes = timerRemaining / 60
        val seconds = timerRemaining % 60
        val clock = if (timerRemaining >= 3600) {
            "%d:%02d:%02d".format(timerRemaining / 3600, minutes % 60, seconds)
        } else {
            "%d:%02d".format(minutes, seconds)
        }
        showCard("计时", clock, "到点会叫醒你")
    }

    private fun renderAlbum() {
        if (albumBitmaps.isEmpty()) return
        keepAwakeForResult()
        resultImage.setImageBitmap(albumBitmaps[albumIndex])
        resultImage.visibility = View.VISIBLE
        resultTitle.visibility = View.GONE
        resultDetail.visibility = View.GONE
        resultKicker.text = "相册 ${albumIndex + 1}/${albumBitmaps.size}"
        resultCard.visibility = View.VISIBLE
        resultCard.alpha = 1f
        setBrightness(WAKE_BRIGHTNESS)
        armSleep()
    }

    private fun showCard(kicker: String, title: String, detail: String) {
        resultImage.visibility = View.GONE
        resultTitle.visibility = View.VISIBLE
        resultKicker.text = kicker
        resultTitle.text = title
        resultTitle.textSize = if (title.length > 10) 28f else 42f
        resultDetail.text = detail
        resultDetail.visibility = if (detail.isBlank()) View.GONE else View.VISIBLE
        resultCard.visibility = View.VISIBLE
        resultCard.alpha = 1f
        setBrightness(WAKE_BRIGHTNESS)
    }

    private fun hideCard() {
        albumBitmaps = emptyList()
        resultImage.setOnClickListener(null)
        resultCard.visibility = View.GONE
        resultImage.setImageDrawable(null)
        resultImage.visibility = View.GONE
        resultTitle.visibility = View.VISIBLE
        resultTitle.text = ""
        resultDetail.text = ""
    }

    private fun enterListening() {
        if (isLabOpen()) return
        pendingWake = false
        heardSpeech = false
        handler.removeCallbacks(sleepRunnable)
        state = State.LISTENING
        waveform.mode = WaveformView.Mode.IDLE
        caption.animate().cancel()
        caption.alpha = 0f
        caption.text = ""
        setBrightness(WAKE_BRIGHTNESS)
        hideWakeHint()
        showSleepHint()
        setCharacterAwake(true)
        faceCharacter.expression = CharacterFaceView.Expression.IDLE
        startListen()
        armSleep()
    }

    private fun showWakeHint(text: String) {
        wakeHint.text = text
        wakeHint.visibility = View.VISIBLE
    }

    private fun hideWakeHint() {
        wakeHint.visibility = View.GONE
    }

    private fun showSleepHint() {
        sleepHint.visibility = View.VISIBLE
    }

    private fun hideSleepHint() {
        sleepHint.visibility = View.GONE
    }

    private fun setCharacterAwake(awake: Boolean) {
        val target = if (awake) 1f else 0.4f
        faceCharacter.animate().cancel()
        faceCharacter.animate().alpha(target).setDuration(220).start()
    }

    private fun armSleep() {
        if (timerRunning) return
        handler.removeCallbacks(sleepRunnable)
        handler.postDelayed(sleepRunnable, IDLE_SLEEP_MS)
    }

    private fun showCaption(text: String) {
        caption.animate().cancel()
        caption.text = text
        caption.alpha = 1f
    }

    private fun setBrightness(value: Float) {
        val params = window.attributes
        params.screenBrightness = value.coerceIn(SLEEP_BRIGHTNESS, 1f)
        window.attributes = params
    }

    fun release() {
        timerRunning = false
        handler.removeCallbacks(sleepRunnable)
        handler.removeCallbacks(tickRunnable)
    }

    companion object {
        const val IDLE_SLEEP_MS = 8_000L
        const val SLEEP_BRIGHTNESS = 0.22f
        const val WAKE_BRIGHTNESS = 0.85f
    }
}
