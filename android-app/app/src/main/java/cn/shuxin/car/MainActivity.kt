package cn.shuxin.car

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import cn.shuxin.car.camera.PhotoAlbum
import cn.shuxin.car.databinding.ActivityMainBinding
import cn.shuxin.car.face.CompanionActions
import cn.shuxin.car.face.FaceController
import cn.shuxin.car.motor.MotorLink
import cn.shuxin.car.motor.NeckController
import cn.shuxin.car.motor.SerialMotorLink
import cn.shuxin.car.network.VoiceClient
import cn.shuxin.car.prefs.DevicePrefs
import org.json.JSONObject
import java.io.File

class MainActivity : AppCompatActivity(), VoiceClient.Listener {
    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: DevicePrefs
    private lateinit var motor: MotorLink
    private lateinit var client: VoiceClient
    private lateinit var face: FaceController
    private lateinit var actions: CompanionActions
    private val logs = ArrayDeque<String>()
    private var labSecrets: Map<String, String> = emptyMap()
    private var debugTaps = 0
    private var debugTapAt = 0L
    private val mainHandler = Handler(Looper.getMainLooper())
    private val shutdownHold = Runnable { actions.shutdown() }
    private val reclaimForeground = Runnable { reclaimIfNeeded() }
    private var lastUtterance = ""
    private var permissionPromptOpen = false
    private var cameraPermissionAsked = false
    private var pendingCameraAction = "look"
    private var splashGone = false
    private val splashTimeout = Runnable { dismissSplash() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        AgentShell.hideSystemBars(this)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        prefs = try {
            DevicePrefs(this)
        } catch (_: Exception) {
            DevicePrefs(applicationContext.createDeviceProtectedStorageContext())
        }
        motor = SerialMotorLink.openOrMock { text -> runOnUiThread { binding.motorText.text = text } }
        client = VoiceClient(this, motor, this)
        face = FaceController(
            window = window,
            waveform = binding.waveform,
            faceCharacter = binding.faceCharacter,
            wakeHint = binding.wakeHint,
            sleepHint = binding.sleepHint,
            caption = binding.caption,
            resultCard = binding.resultCard,
            resultKicker = binding.resultKicker,
            resultTitle = binding.resultTitle,
            resultDetail = binding.resultDetail,
            resultImage = binding.resultImage,
            startListen = {
                if (!hasMicPermission()) {
                    face.showNotice("听不见")
                } else {
                    lastUtterance = ""
                    client.startListen()
                }
            },
            cancelTurn = { client.cancelListen() },
            isReady = { client.isReady() },
            isLabOpen = { binding.labRoot.visibility == View.VISIBLE },
            connectNow = {
                if (!client.isReady()) {
                    connectFromPrefs()
                }
            },
            onTimerFired = { beep() },
        )
        actions = CompanionActions(
            prefs,
            face,
            camera = cn.shuxin.car.camera.CameraCapture(this, binding.cameraPreview),
            sendVision = { jpeg -> client.sendVision(jpeg) },
            neck = NeckController(motor, mainHandler),
            album = PhotoAlbum(File(filesDir, "album")),
        )
        face.attach()
        AgentShell.applyOwnerKiosk(this)
        binding.bootLogo.setOnClickListener { dismissSplash() }
        mainHandler.postDelayed(splashTimeout, SPLASH_MS)
        mainHandler.postDelayed({ ensureRuntimePermissions() }, SPLASH_MS + 80)
        labSecrets = loadLabSecrets()
        fillLabFields()
        AgentShell.watchInsets(this)
        onBackPressedDispatcher.addCallback(
            this,
            object : OnBackPressedCallback(true) {
                override fun handleOnBackPressed() {
                    if (binding.labRoot.visibility == View.VISIBLE) {
                        closeLab()
                    }
                }
            },
        )
        binding.root.postDelayed({ maybeLookExtra(intent) }, 800)

        binding.waveform.isClickable = true
        binding.waveform.setOnTouchListener { _, event -> handleFaceTouch(event) }
        binding.root.setOnTouchListener { _, event -> handleFaceTouch(event) }
        binding.wakeHint.setOnClickListener { face.wake() }
        binding.sleepHint.setOnClickListener { face.sleep(force = true) }
        binding.connectBtn.setOnClickListener {
            savePrefs()
            connectFromPrefs()
        }
        binding.closeLabBtn.setOnClickListener { closeLab() }
        binding.powerOffBtn.setOnClickListener { actions.shutdown() }
        binding.stopBtn.setOnClickListener { client.abortAndStop() }
        binding.talkBtn.setOnTouchListener { view, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    if (!hasMicPermission()) {
                        requestMicPermission()
                    } else {
                        view.isPressed = true
                        binding.talkBtn.text = "正在听…"
                        client.startListen()
                    }
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    view.isPressed = false
                    binding.talkBtn.text = "处理中"
                    client.stopListen()
                    true
                }
                else -> false
            }
        }
        connectFromPrefs()
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        maybeLookExtra(intent)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            AgentShell.hideSystemBars(this)
            AgentShell.applyOwnerKiosk(this)
        }
    }

    override fun onResume() {
        super.onResume()
        mainHandler.removeCallbacks(reclaimForeground)
        AgentShell.hideSystemBars(this)
        AgentShell.applyOwnerKiosk(this)
    }

    override fun onStop() {
        super.onStop()
        if (!isChangingConfigurations) {
            mainHandler.postDelayed(reclaimForeground, 350)
        }
    }

    override fun onDestroy() {
        mainHandler.removeCallbacks(shutdownHold)
        mainHandler.removeCallbacks(reclaimForeground)
        mainHandler.removeCallbacks(splashTimeout)
        face.release()
        motor.stopLink()
        client.disconnect()
        super.onDestroy()
    }

    private fun handleFaceTouch(event: MotionEvent): Boolean {
        if (binding.labRoot.visibility == View.VISIBLE) return false
        when (event.actionMasked) {
            MotionEvent.ACTION_POINTER_DOWN -> {
                if (event.pointerCount >= 2) {
                    mainHandler.removeCallbacks(shutdownHold)
                    client.abortAndStop()
                    face.wake()
                    return true
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                mainHandler.removeCallbacks(shutdownHold)
                return true
            }
            MotionEvent.ACTION_DOWN -> {
                mainHandler.removeCallbacks(shutdownHold)
                mainHandler.postDelayed(shutdownHold, 2500)
                if (!hasMicPermission()) {
                    face.showNotice("听不见")
                    ensureMicPermission()
                } else {
                    face.wake()
                }
            }
            else -> return true
        }
        if (event.actionMasked != MotionEvent.ACTION_DOWN) return true
        val corner = event.x > binding.root.width - dp(120f) && event.y < dp(120f)
        val now = SystemClock.elapsedRealtime()
        if (corner && now - debugTapAt < 900) {
            debugTaps += 1
        } else {
            debugTaps = if (corner) 1 else 0
        }
        debugTapAt = now
        if (debugTaps >= 5) {
            debugTaps = 0
            mainHandler.removeCallbacks(shutdownHold)
            openLab()
            return true
        }
        return true
    }

    private fun hasCameraPermission(): Boolean {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun openLab() {
        client.cancelListen()
        binding.wakeHint.visibility = View.GONE
        binding.sleepHint.visibility = View.GONE
        binding.labRoot.visibility = View.VISIBLE
        setBrightness(0.7f)
    }

    private fun closeLab() {
        savePrefs()
        binding.labRoot.visibility = View.GONE
        AgentShell.hideSystemBars(this)
        face.sleep()
    }

    private fun connectFromPrefs() {
        val code = binding.deviceCode.text.toString().ifBlank { DevicePrefs.DEFAULT_DEVICE_CODE }
        val userName = binding.deviceSecret.text.toString().ifBlank { DevicePrefs.DEFAULT_USER_NAME }
        client.connect(
            binding.wsUrl.text.toString().ifBlank { DevicePrefs.DEFAULT_WS },
            userName,
            code,
            labSecrets,
        )
    }

    private fun fillLabFields() {
        val ws = prefs.wsUrl
        val labLocal = ws.isBlank() || "shuxinzzx.com.cn" in ws || "192.168.1.4" in ws
        binding.wsUrl.setText(if (labLocal) DevicePrefs.DEFAULT_WS else ws)
        if (labLocal) prefs.wsUrl = DevicePrefs.DEFAULT_WS
        val savedCode = prefs.deviceCode
        val savedName = prefs.userName
        binding.deviceCode.setText(
            if (savedCode.isBlank() || savedCode.contains("admin", ignoreCase = true)) {
                DevicePrefs.DEFAULT_DEVICE_CODE
            } else {
                savedCode
            },
        )
        binding.deviceSecret.setText(
            if (savedName.isBlank() || savedName.contains("admin", ignoreCase = true) || savedName.equals("k11c", true)) {
                DevicePrefs.DEFAULT_USER_NAME
            } else {
                savedName
            },
        )
    }

    private fun savePrefs() {
        prefs.wsUrl = binding.wsUrl.text.toString()
        prefs.deviceCode = binding.deviceCode.text.toString()
        prefs.userName = binding.deviceSecret.text.toString()
    }

    private fun loadLabSecrets(): Map<String, String> {
        val out = linkedMapOf<String, String>()
        try {
            assets.open("lab_device_secrets.properties").bufferedReader().useLines { lines ->
                lines.forEach { line ->
                    val text = line.trim()
                    if (text.isEmpty() || text.startsWith("#")) return@forEach
                    val index = text.indexOf('=')
                    if (index > 0) {
                        out[text.substring(0, index).trim()] = text.substring(index + 1)
                    }
                }
            }
        } catch (_: Exception) {
            // Lab pin file is generated locally and gitignored.
        }
        return out
    }

    private fun reclaimIfNeeded() {
        if (isFinishing || isDestroyed) return
        if (permissionPromptOpen) return
        if (binding.labRoot.visibility == View.VISIBLE) return
        startActivity(AgentShell.launchIntent(this))
    }

    private fun setBrightness(value: Float) {
        val params = window.attributes
        params.screenBrightness = value
        window.attributes = params
    }

    private fun beep() {
        runCatching {
            val tone = ToneGenerator(AudioManager.STREAM_MUSIC, 80)
            tone.startTone(ToneGenerator.TONE_PROP_BEEP2, 900)
            binding.root.postDelayed({ runCatching { tone.release() } }, 1200)
        }
    }

    private fun dp(value: Float): Float = value * resources.displayMetrics.density

    private fun hasMicPermission(): Boolean {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
    }

    private fun ensureRuntimePermissions() {
        val needed = mutableListOf<String>()
        if (!hasMicPermission()) needed.add(Manifest.permission.RECORD_AUDIO)
        if (!hasCameraPermission()) needed.add(Manifest.permission.CAMERA)
        if (needed.isEmpty()) return
        permissionPromptOpen = true
        cameraPermissionAsked = needed.contains(Manifest.permission.CAMERA)
        ActivityCompat.requestPermissions(this, needed.toTypedArray(), 19)
    }

    private fun ensureMicPermission() {
        ensureRuntimePermissions()
    }

    private fun requestMicPermission() {
        ensureMicPermission()
    }

    private fun requestCameraPermission() {
        cameraPermissionAsked = true
        permissionPromptOpen = true
        ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), 18)
    }

    private fun lookOrRequestCamera() {
        withCamera("look")
    }

    private fun withCamera(action: String) {
        pendingCameraAction = action
        if (hasCameraPermission()) {
            runCameraAction(action)
            return
        }
        if (cameraPermissionAsked) {
            face.showNotice("看不见")
            return
        }
        requestCameraPermission()
    }

    private fun runCameraAction(action: String) {
        when (action) {
            "photo" -> actions.photo()
            "look_around" -> actions.lookAround()
            else -> actions.look()
        }
    }

    private fun dismissSplash() {
        if (splashGone) return
        splashGone = true
        mainHandler.removeCallbacks(splashTimeout)
        binding.bootLogo.animate()
            .alpha(0f)
            .setDuration(360)
            .withEndAction { binding.bootLogo.visibility = View.GONE }
            .start()
    }

    private fun maybeLookExtra(intent: android.content.Intent?) {
        if (intent?.getBooleanExtra("look", false) == true && hasCameraPermission()) {
            actions.look()
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        permissionPromptOpen = false
        val granted = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        if (requestCode == 19) {
            if (!hasMicPermission()) face.showNotice("听不见")
            if (!hasCameraPermission() && cameraPermissionAsked) face.showNotice("看不见")
            return
        }
        if (requestCode == 17) {
            if (granted) face.wake() else face.showNotice("听不见")
        }
        if (requestCode == 18) {
            if (granted) runCameraAction(pendingCameraAction) else face.showNotice("看不见")
        }
    }

    override fun onStatus(text: String) = runOnUiThread {
        binding.statusText.text = text
        if (text == "已断开") face.onDisconnected()
    }
    override fun onBound(text: String) = runOnUiThread { binding.boundText.text = text }
    override fun onStt(text: String) = runOnUiThread {
        binding.sttText.text = text
        face.onStt(text)
    }
    override fun onReply(text: String, append: Boolean) = runOnUiThread {
        binding.replyText.text = text
        face.onReply(text)
    }
    override fun onMotor(text: String) = runOnUiThread { binding.motorText.text = text }
    override fun onLog(text: String) = runOnUiThread {
        logs.addLast(text)
        while (logs.size > 8) logs.removeFirst()
        binding.logText.text = logs.joinToString("\n")
    }
    override fun onTalkEnabled(enabled: Boolean) = runOnUiThread {
        binding.talkBtn.isEnabled = enabled
        if (enabled) binding.talkBtn.text = "按住说话"
    }
    override fun onError(text: String) = runOnUiThread {
        binding.statusText.text = text
        face.onError(text)
        if (binding.labRoot.visibility == View.VISIBLE) {
            Toast.makeText(this, text, Toast.LENGTH_SHORT).show()
        }
    }
    override fun onReady() = runOnUiThread { face.onReady() }
    override fun onSpeechStarted() = runOnUiThread {
        face.onSpeechStarted()
    }
    override fun onListenEnded() = runOnUiThread {
        face.onListenEnded()
    }
    override fun onListenIgnored() = runOnUiThread {
        face.onListenIgnored()
    }
    override fun onSpeaking() = runOnUiThread { face.onSpeaking() }
    override fun onPlaybackIdle() = runOnUiThread { face.onPlaybackIdle() }
    override fun onWaveform(samples: FloatArray, playback: Boolean) = runOnUiThread {
        face.onWaveform(samples, playback)
    }
    override fun onLookHint() = runOnUiThread { lookOrRequestCamera() }
    override fun onUtterance(text: String) = runOnUiThread {
        lastUtterance = text
        actions.handleUtterance(text)
    }
    override fun onScreenTool(name: String, args: JSONObject): Boolean {
        runOnUiThread {
            when (name) {
                "self.clock.set_timer" -> {
                    val seconds = if (args.has("seconds") && args.optInt("seconds") > 0) {
                        args.optInt("seconds")
                    } else {
                        (args.optDouble("minutes", 0.0) * 60).toInt()
                    }
                    if (seconds >= 5) actions.startTimer(seconds)
                }
                "self.display.weather" -> {
                    val temperature = if (args.has("temperature")) args.optInt("temperature") else null
                    actions.showWeather(
                        args.optString("region").ifBlank { null },
                        temperature,
                        args.optString("summary").ifBlank { null },
                    )
                }
                "self.camera.look" -> withCamera("look")
                "self.camera.look_around" -> withCamera("look_around")
                "self.camera.photo" -> withCamera("photo")
                "self.camera.album" -> actions.showAlbum()
                "self.head.nod" -> actions.nod()
                "self.head.shake" -> actions.shake()
                "self.head.turn" -> actions.turnHead(args.optInt("pan", 90), args.optInt("tilt", 90))
            }
        }
        return name in SCREEN_TOOLS
    }

    companion object {
        private const val SPLASH_MS = 400L
        private val SCREEN_TOOLS = setOf(
            "self.clock.set_timer",
            "self.display.weather",
            "self.camera.look",
            "self.camera.look_around",
            "self.camera.photo",
            "self.camera.album",
            "self.head.nod",
            "self.head.shake",
            "self.head.turn",
        )
    }
}
