package cn.shuxin.car.network

import cn.shuxin.car.audio.AudioIo
import cn.shuxin.car.audio.OpusBridge
import cn.shuxin.car.mcp.McpHandler
import cn.shuxin.car.motor.MotorLink
import cn.shuxin.car.face.CompanionIntent
import cn.shuxin.car.face.CompanionIntents
import cn.shuxin.car.face.EnergyVad
import cn.shuxin.car.face.FillerSpeech
import cn.shuxin.car.face.PcmLevel
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

class VoiceClient(
    context: android.content.Context,
    private val motor: MotorLink,
    private val listener: Listener,
) {
    interface Listener {
        fun onStatus(text: String)
        fun onBound(text: String)
        fun onStt(text: String)
        fun onReply(text: String, append: Boolean)
        fun onMotor(text: String)
        fun onLog(text: String)
        fun onTalkEnabled(enabled: Boolean)
        fun onError(text: String)
        fun onReady()
        fun onSpeechStarted()
        fun onListenEnded()
        fun onListenIgnored()
        fun onSpeaking()
        fun onPlaybackIdle()
        fun onWaveform(samples: FloatArray, playback: Boolean)
        fun onUtterance(text: String)
        fun onLookHint()
        fun onScreenTool(name: String, args: org.json.JSONObject): Boolean
    }

    private val http = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val opus = OpusBridge()
    private val vad = EnergyVad()
    private val listening = AtomicBoolean(false)
    private val listenAcked = AtomicBoolean(false)
    private val heardSpeech = AtomicBoolean(false)
    private val awaitingDrain = AtomicBoolean(false)
    private val ready = AtomicBoolean(false)
    private var vadArmedAt = 0L
    private var lastAsrText = ""
    private val uplinkFrames = AtomicInteger(0)
    private val audio = AudioIo(
        context,
        opus,
        onEncodedFrame = { packet ->
            uplinkFrames.incrementAndGet()
            socket?.send(ByteString.of(*packet))
        },
        onError = { listener.onError(it) },
        onMicPcm = { pcm -> onMicFrame(pcm) },
        onPlayPcm = { pcm -> ui { listener.onWaveform(PcmLevel.downsample(pcm), true) } },
        onPlaybackIdle = {
            if (awaitingDrain.compareAndSet(true, false)) {
                ui { listener.onPlaybackIdle() }
            }
        },
    )
    private val mcp = McpHandler(
        motor = motor,
        sendJson = { sendJson(it) },
        onMotorUi = { listener.onMotor(it) },
        onScreenCall = { name, args -> listener.onScreenTool(name, args) },
    )

    private var socket: WebSocket? = null
    private val open = AtomicBoolean(false)
    private var replyBuffer = ""
    private val pingExec = Executors.newSingleThreadScheduledExecutor()
    private var pingTask: ScheduledFuture<*>? = null
    private val listenWatchdog = Runnable {
        if (listening.get()) stopListen()
    }
    private val mainHandler = Handler(Looper.getMainLooper())

    private fun ui(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) block() else mainHandler.post(block)
    }

    fun connect(url: String, userName: String, robotCode: String, labSecrets: Map<String, String> = emptyMap()) {
        disconnect()
        val name = userName.trim()
        val code = robotCode.trim()
        if (name.isBlank() || code.isBlank()) {
            listener.onError("请填写用户名和机器人代号（例如 小林 + SX-000003）。")
            return
        }
        if (looksLikeAdminToken(name) || looksLikeAdminToken(code)) {
            listener.onError("不要填后台 Admin Token。用户名用人名，代号用 SX-000003 这类设备号。")
            return
        }
        listener.onStatus("连接中…")
        val req = Request.Builder().url(url.trim()).build()
        socket = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                open.set(true)
                ready.set(false)
                startPing()
                listener.onStatus("已连接，正在 hello")
                sendJson(
                    JSONObject()
                        .put("type", "hello")
                        .put("user_name", name)
                        .put("robot_code", code)
                        .put("client_id", "rk3566-android")
                        .put(
                            "features",
                            JSONObject()
                                .put("mcp", true)
                                .put("camera", true),
                        )
                        .put(
                            "audio_params",
                            JSONObject()
                                .put("format", "opus")
                                .put("sample_rate", 16000)
                                .put("channels", 1)
                                .put("frame_duration", 60),
                        ),
                )
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleText(text)
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                audio.enqueueDownlink(bytes.toByteArray())
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                open.set(false)
                ready.set(false)
                listening.set(false)
                stopPing()
                audio.stopRecording()
                listener.onTalkEnabled(false)
                listener.onStatus("已断开")
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                open.set(false)
                ready.set(false)
                listening.set(false)
                stopPing()
                audio.stopRecording()
                listener.onTalkEnabled(false)
                listener.onError(humanizeError(t.message ?: "连接失败"))
            }
        })
    }

    fun disconnect() {
        open.set(false)
        ready.set(false)
        listening.set(false)
        stopPing()
        audio.stopRecording()
        audio.stopPlayback()
        socket?.close(1000, "bye")
        socket = null
        listener.onTalkEnabled(false)
    }

    fun isOpen(): Boolean = open.get()

    fun isReady(): Boolean = ready.get()

    fun isConnecting(): Boolean = socket != null && !ready.get()

    fun startListen() {
        if (!ready.get()) return
        if (!listening.compareAndSet(false, true)) return
        replyBuffer = ""
        heardSpeech.set(false)
        lastAsrText = ""
        listenAcked.set(false)
        uplinkFrames.set(0)
        vad.reset()
        vadArmedAt = SystemClock.elapsedRealtime() + 280
        listener.onStt("…")
        listener.onReply("—", false)
        audio.stopPlayback()
        sendJson(JSONObject().put("type", "listen").put("state", "start"))
        audio.startRecording()
        mainHandler.removeCallbacks(listenWatchdog)
        mainHandler.postDelayed(listenWatchdog, LISTEN_MAX_MS)
    }

    fun stopListen() {
        mainHandler.removeCallbacks(listenWatchdog)
        if (!listening.getAndSet(false)) {
            audio.stopRecording()
            return
        }
        audio.stopRecording()
        sendJson(JSONObject().put("type", "listen").put("state", "stop"))
        listener.onListenEnded()
    }

    fun cancelListen() {
        mainHandler.removeCallbacks(listenWatchdog)
        val was = listening.getAndSet(false)
        audio.stopRecording()
        if (was && open.get()) {
            sendJson(JSONObject().put("type", "abort"))
        }
    }

    fun abortAndStop() {
        mainHandler.removeCallbacks(listenWatchdog)
        listening.set(false)
        motor.emergencyStop()
        sendJson(JSONObject().put("type", "abort"))
        audio.stopRecording()
        audio.stopPlayback()
    }

    fun sendVision(jpeg: ByteArray) {
        if (!open.get() || jpeg.isEmpty()) return
        val encoded = android.util.Base64.encodeToString(jpeg, android.util.Base64.NO_WRAP)
        sendJson(
            JSONObject()
                .put("type", "vision")
                .put("mime", "image/jpeg")
                .put("image_base64", encoded),
        )
    }

    private fun handleText(text: String) {
        val msg = JSONObject(text)
        val type = msg.optString("type")
        when (type) {
            "hello" -> {
                if (msg.optString("state") == "ok") {
                    val user = msg.optString("user_id", "-")
                    val device = msg.optString("device_id", "-")
                    listener.onBound("绑定：$user / $device")
                    if (msg.optBoolean("factory_acceptance", false)) {
                        listener.onStatus("工厂验收模式（不能对话）")
                        listener.onTalkEnabled(false)
                    } else {
                        ready.set(true)
                        listener.onStatus("已就绪")
                        listener.onTalkEnabled(true)
                        listener.onReady()
                    }
                }
            }
            "listen" -> {
                if (msg.optString("state") == "start") listenAcked.set(true)
            }
            "error" -> {
                val message = humanizeError(msg.optString("message", "error"))
                listener.onTalkEnabled(ready.get())
                if ("没听清" in message || "再说一次" in message || "刚才卡住" in message) {
                    listener.onListenIgnored()
                } else {
                    listener.onError(message)
                }
            }
            "stt" -> {
                val state = msg.optString("state")
                val text = msg.optString("text", "—")
                if (state == "ignored" || FillerSpeech.isFiller(text)) {
                    if (state in setOf("ignored", "final", "stream_final")) {
                        listener.onListenIgnored()
                    }
                    return
                }
                if (state in setOf("partial", "sentence_final", "stream_final", "final")) {
                    listener.onStt(text)
                    if (text.isNotBlank() && text != "—") lastAsrText = text
                }
                if (state in setOf("final", "stream_final") && text.isNotBlank() && text != "—") {
                    listener.onUtterance(text)
                }
            }
            "agent" -> {
                when (msg.optString("state")) {
                    "delta" -> {
                        replyBuffer += msg.optString("text")
                        listener.onReply(replyBuffer.ifBlank { "—" }, false)
                    }
                    "reply" -> listener.onReply(msg.optString("text", "—"), false)
                    "error" -> listener.onError("Agent: ${msg.optString("error_kind", "error")}")
                }
            }
            "tts" -> {
                when (msg.optString("state")) {
                    "sentence_start" -> {
                        awaitingDrain.set(false)
                        listener.onSpeaking()
                    }
                    "stop" -> {
                        listener.onTalkEnabled(true)
                        awaitingDrain.set(true)
                        if (!audio.isBusy()) {
                            awaitingDrain.set(false)
                            listener.onPlaybackIdle()
                        }
                    }
                }
            }
            "mcp" -> mcp.handle(msg)
            "factory_verify" -> {
                listener.onStatus("工厂验收 PASS")
                sendJson(
                    JSONObject()
                        .put("type", "factory_verify_ack")
                        .put("verify_id", msg.optString("verify_id"))
                        .put("status", "ok"),
                )
            }
            "ping" -> sendJson(JSONObject().put("type", "pong"))
        }
        if (type != "agent" || msg.optString("state") != "delta") {
            listener.onLog(type.ifBlank { "msg" })
        }
    }

    private fun sendJson(obj: JSONObject) {
        socket?.send(obj.toString())
    }

    private fun startPing() {
        stopPing()
        pingTask = pingExec.scheduleAtFixedRate(
            { sendJson(JSONObject().put("type", "ping")) },
            20,
            20,
            TimeUnit.SECONDS,
        )
    }

    private fun stopPing() {
        pingTask?.cancel(false)
        pingTask = null
    }

    private fun onMicFrame(pcm: ByteArray) {
        ui { listener.onWaveform(PcmLevel.downsampleBytes(pcm), false) }
        if (!listening.get()) return
        if (SystemClock.elapsedRealtime() < vadArmedAt) return
        when (vad.onRms(PcmLevel.rmsBytes(pcm))) {
            EnergyVad.Event.SPEECH_START -> {
                heardSpeech.set(true)
                mainHandler.removeCallbacks(listenWatchdog)
                mainHandler.postDelayed(listenWatchdog, SPEECH_MAX_MS)
                ui { listener.onSpeechStarted() }
            }
            EnergyVad.Event.SPEECH_END -> mainHandler.post {
                if (uplinkFrames.get() < 2 && !heardSpeech.get()) return@post
                if (CompanionIntents.parse(lastAsrText) is CompanionIntent.Look) {
                    listener.onLookHint()
                }
                stopListen()
            }
            EnergyVad.Event.NONE -> Unit
        }
    }

    companion object {
        private const val LISTEN_MAX_MS = 4_500L
        private const val SPEECH_MAX_MS = 3_500L

        private fun looksLikeAdminToken(value: String): Boolean {
            val text = value.trim().lowercase()
            return text.contains("admin-token") || text == "admin" || text.startsWith("dev-admin")
        }

        private fun humanizeError(message: String): String {
            val text = message.lowercase()
            return when {
                "invalid device secret" in text ->
                    "设备密钥不对。请到 Admin「加载设备」复制这一台的密钥。"
                "not bound" in text ->
                    "设备还没绑定用户，先在后台绑定再连。"
                "not authenticated" in text || "select target" in text ->
                    "还没登录上，等连好再说。"
                "no audio" in text || "没听清" in text ->
                    "没听清，再说一次"
                "刚才卡住" in text ->
                    "刚才卡住了，再说一次"
                "not found" in text ->
                    "设备编号不存在。不要填 Admin Token，请填 SX-000003 这类编号。"
                "unreachable" in text || "network is unreachable" in text ||
                    "failed to connect" in text || "econnrefused" in text ||
                    "timed out" in text || "timeout" in text ||
                    "unable to resolve" in text || "no address" in text ->
                    "没网，连不上"
                else -> message
            }
        }
    }
}
