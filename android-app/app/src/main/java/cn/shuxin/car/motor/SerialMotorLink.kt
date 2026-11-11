package cn.shuxin.car.motor

import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Talks to the ESP32-C3 TB6612 firmware over UART7.
 * Firmware protocol is ASCII lines (`F 55`, `S`, …) at 115200 8N1, not the binary CRC frames.
 */
class SerialMotorLink(
    private val port: File,
    private val onStatus: (String) -> Unit,
) : MotorLink {
    private val executor = Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "motor-uart").apply { isDaemon = true }
    }
    private val started = AtomicBoolean(false)
    private var output: FileOutputStream? = null
    private var stopFuture: ScheduledFuture<*>? = null
    private var refreshFuture: ScheduledFuture<*>? = null
    @Volatile
    private var lastMove: String = "S"

    @Volatile
    override var ready: Boolean = false
        private set

    override fun start() {
        if (!started.compareAndSet(false, true)) return
        configureBaud(port.path)
        output = FileOutputStream(port)
        ready = true
        executor.execute {
            sendLocked("S")
            onStatus("电机：${port.name} / 停")
        }
    }

    override fun stopLink() {
        if (executor.isShutdown) return
        executor.execute {
            cancelTimersLocked()
            sendLocked("S")
            runCatching { output?.close() }
            output = null
            ready = false
            onStatus("电机：${port.name} / 关闭")
        }
        executor.shutdown()
    }

    override fun setMotor(left: Int, right: Int, durationMs: Int) {
        val line = ChassisSerial.encode(left, right)
        val holdMs = durationMs.coerceIn(0, 4000)
        executor.execute {
            if (!ready) return@execute
            cancelTimersLocked()
            lastMove = line
            sendLocked(line)
            onStatus("电机：$line ${holdMs}ms")
            if (line == "S" || holdMs <= 0) return@execute
            refreshFuture = executor.scheduleAtFixedRate(
                { sendLocked(lastMove) },
                REFRESH_MS,
                REFRESH_MS,
                TimeUnit.MILLISECONDS,
            )
            stopFuture = executor.schedule({
                cancelTimersLocked()
                lastMove = "S"
                sendLocked("S")
                onStatus("电机：${port.name} / 停")
            }, holdMs.toLong(), TimeUnit.MILLISECONDS)
        }
    }

    override fun emergencyStop() {
        executor.execute {
            cancelTimersLocked()
            lastMove = "S"
            sendLocked("S")
            onStatus("电机：急停")
        }
    }

    override fun sendCommand(line: String) {
        val text = line.trim()
        if (text.isEmpty()) return
        executor.execute {
            if (!ready) return@execute
            sendLocked(text)
            onStatus("电机：$text")
        }
    }

    private fun cancelTimersLocked() {
        stopFuture?.cancel(false)
        refreshFuture?.cancel(false)
        stopFuture = null
        refreshFuture = null
    }

    private fun sendLocked(line: String) {
        val stream = output ?: return
        try {
            stream.write("$line\n".toByteArray(Charsets.US_ASCII))
            stream.flush()
        } catch (t: Throwable) {
            Log.w(TAG, "uart write failed", t)
            ready = false
            onStatus("电机：串口写入失败")
        }
    }

    companion object {
        private const val TAG = "SerialMotor"
        private const val REFRESH_MS = 100L
        val CANDIDATES = listOf("/dev/ttyS7", "/dev/ttyS4", "/dev/ttyS1")

        fun openOrMock(onStatus: (String) -> Unit): MotorLink {
            for (path in CANDIDATES) {
                val file = File(path)
                if (!file.exists()) continue
                try {
                    return SerialMotorLink(file, onStatus).also { it.start() }
                } catch (t: Throwable) {
                    Log.w(TAG, "open $path failed", t)
                }
            }
            onStatus("电机：无串口，模拟")
            return MockMotorLink(onStatus).also { it.start() }
        }

        internal fun configureBaud(path: String) {
            val attempts = listOf(
                arrayOf("stty", "-F", path, "115200", "raw", "-echo", "-ixon", "-ixoff"),
                arrayOf("sh", "-c", "stty -F $path 115200 raw -echo -ixon -ixoff"),
            )
            for (cmd in attempts) {
                try {
                    val proc = Runtime.getRuntime().exec(cmd)
                    if (proc.waitFor() == 0) return
                } catch (_: Exception) {
                }
            }
        }
    }
}
