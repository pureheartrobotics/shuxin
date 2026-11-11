package cn.shuxin.car.audio

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class AudioIo(
    context: Context,
    private val opus: OpusBridge,
    private val onEncodedFrame: (ByteArray) -> Unit,
    private val onError: (String) -> Unit,
    private val onMicPcm: (ByteArray) -> Unit = {},
    private val onPlayPcm: (ShortArray) -> Unit = {},
    private val onPlaybackIdle: () -> Unit = {},
) {
    private val appContext = context.applicationContext
    private val audioManager = appContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val recording = AtomicBoolean(false)
    private val playing = AtomicBoolean(false)
    private val packetQueue = LinkedBlockingQueue<ByteArray>(256)
    private var recordThread: Thread? = null
    private var playThread: Thread? = null
    private var focusRequest: AudioFocusRequest? = null

    @SuppressLint("MissingPermission")
    fun startRecording() {
        if (!recording.compareAndSet(false, true)) return
        recordThread = Thread({
            val min = AudioRecord.getMinBufferSize(
                OpusBridge.UPLINK_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            val recorder = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                OpusBridge.UPLINK_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(min, OpusBridge.UPLINK_FRAME_BYTES * 4),
            )
            try {
                recorder.startRecording()
                val buf = ByteArray(OpusBridge.UPLINK_FRAME_BYTES)
                while (recording.get()) {
                    var filled = 0
                    while (recording.get() && filled < buf.size) {
                        val n = recorder.read(buf, filled, buf.size - filled)
                        if (n <= 0) break
                        filled += n
                    }
                    if (filled < buf.size) continue
                    onMicPcm(buf)
                    val packet = opus.encodeUplink(buf) ?: continue
                    onEncodedFrame(packet)
                }
            } catch (t: Throwable) {
                onError("录音失败: ${t.message}")
            } finally {
                runCatching { recorder.stop() }
                recorder.release()
                recording.set(false)
            }
        }, "mic-uplink").also { it.start() }
    }

    fun stopRecording() {
        recording.set(false)
        recordThread?.join(400)
        recordThread = null
    }

    fun enqueueDownlink(packet: ByteArray) {
        if (packet.isEmpty()) return
        if (!packetQueue.offer(packet)) {
            runCatching { packetQueue.offer(packet, 250, TimeUnit.MILLISECONDS) }
        }
        ensurePlayer()
    }

    fun isBusy(): Boolean = playing.get() || packetQueue.isNotEmpty()

    fun beginUtterance() {
        opus.resetDecoder()
    }

    fun stopPlayback() {
        playing.set(false)
        packetQueue.clear()
        playThread?.interrupt()
        playThread?.join(400)
        playThread = null
        opus.resetDecoder()
        abandonFocus()
    }

    private fun ensurePlayer() {
        if (!playing.compareAndSet(false, true)) return
        playThread = Thread({
            prepareSpeaker()
            val min = AudioTrack.getMinBufferSize(
                OpusBridge.PLAY_RATE,
                AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            val track = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build(),
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(OpusBridge.PLAY_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .build(),
                )
                .setBufferSizeInBytes(
                    maxOf(min * 12, OpusBridge.PLAY_FRAME_SAMPLES * 2 * PREROLL_PACKETS * 4),
                )
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
            try {
                var waited = 0
                while (
                    playing.get() &&
                    packetQueue.size < PREROLL_PACKETS &&
                    waited < PREROLL_WAIT_MS
                ) {
                    Thread.sleep(10)
                    waited += 10
                }
                if (packetQueue.isEmpty()) {
                    while (playing.get() && packetQueue.isEmpty() && waited < PREROLL_WAIT_MS + 400) {
                        Thread.sleep(10)
                        waited += 10
                    }
                }
                track.play()
                var idlePolls = 0
                var everPlayed = false
                while (playing.get()) {
                    val packet = packetQueue.poll(50, TimeUnit.MILLISECONDS)
                    if (packet == null) {
                        idlePolls++
                        if (everPlayed && idlePolls >= IDLE_POLLS) {
                            everPlayed = false
                            onPlaybackIdle()
                        }
                        continue
                    }
                    idlePolls = 0
                    val pcm = opus.decodeDownlink(packet) ?: continue
                    everPlayed = true
                    onPlayPcm(pcm)
                    track.write(pcm, 0, pcm.size, AudioTrack.WRITE_BLOCKING)
                }
            } catch (t: Throwable) {
                if (playing.get()) onError("播放失败: ${t.message}")
            } finally {
                runCatching { track.stop() }
                track.release()
                playing.set(false)
                abandonFocus()
            }
        }, "tts-downlink").also { it.start() }
    }

    private fun prepareSpeaker() {
        val max = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val target = (max * 2 / 3).coerceAtLeast(1)
        audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, target, 0)
        audioManager.mode = AudioManager.MODE_NORMAL
        audioManager.isSpeakerphoneOn = false
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            .setAcceptsDelayedFocusGain(false)
            .build()
        focusRequest = request
        audioManager.requestAudioFocus(request)
    }

    private fun abandonFocus() {
        val request = focusRequest ?: return
        audioManager.abandonAudioFocusRequest(request)
        focusRequest = null
    }

    companion object {
        private const val PREROLL_PACKETS = 6
        private const val PREROLL_WAIT_MS = 420
        private const val IDLE_POLLS = 18
    }
}
