package cn.shuxin.car.audio

import io.github.jaredmdobson.concentus.OpusApplication
import io.github.jaredmdobson.concentus.OpusDecoder
import io.github.jaredmdobson.concentus.OpusEncoder
import java.nio.ByteBuffer
import java.nio.ByteOrder

class OpusBridge {
    private val encoder = OpusEncoder(UPLINK_RATE, 1, OpusApplication.OPUS_APPLICATION_VOIP).apply {
        bitrate = 16_000
        complexity = 5
    }
    private val decoder = OpusDecoder(PLAY_RATE, 1)
    private val encodeBuf = ByteArray(4000)
    private val pcmShorts = ShortArray(UPLINK_FRAME_SAMPLES)

    @Synchronized
    fun encodeUplink(pcm16le: ByteArray): ByteArray? {
        if (pcm16le.size < UPLINK_FRAME_BYTES) return null
        ByteBuffer.wrap(pcm16le, 0, UPLINK_FRAME_BYTES)
            .order(ByteOrder.LITTLE_ENDIAN)
            .asShortBuffer()
            .get(pcmShorts)
        val n = try {
            encoder.encode(pcmShorts, 0, UPLINK_FRAME_SAMPLES, encodeBuf, 0, encodeBuf.size)
        } catch (_: Exception) {
            return null
        }
        return if (n > 0) encodeBuf.copyOf(n) else null
    }

    @Synchronized
    fun decodeDownlink(packet: ByteArray): ShortArray? {
        if (packet.isEmpty()) return null
        val pcm = ShortArray(PLAY_FRAME_SAMPLES)
        val samples = try {
            decoder.decode(packet, 0, packet.size, pcm, 0, PLAY_FRAME_SAMPLES, false)
        } catch (_: Exception) {
            return null
        }
        if (samples <= 0) return null
        return if (samples == pcm.size) pcm else pcm.copyOf(samples)
    }

    @Synchronized
    fun resetDecoder() {
        runCatching { decoder.resetState() }
    }

    companion object {
        const val UPLINK_RATE = 16_000
        const val DOWNLINK_RATE = 24_000
        const val PLAY_RATE = 48_000
        const val FRAME_MS = 60
        const val UPLINK_FRAME_SAMPLES = UPLINK_RATE * FRAME_MS / 1000
        const val DOWNLINK_FRAME_SAMPLES = DOWNLINK_RATE * FRAME_MS / 1000
        const val PLAY_FRAME_SAMPLES = PLAY_RATE * FRAME_MS / 1000
        const val UPLINK_FRAME_BYTES = UPLINK_FRAME_SAMPLES * 2
    }
}
