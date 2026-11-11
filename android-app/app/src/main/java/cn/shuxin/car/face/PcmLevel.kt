package cn.shuxin.car.face

import kotlin.math.sqrt

object PcmLevel {
    fun rmsBytes(pcm16le: ByteArray): Double {
        val n = pcm16le.size / 2
        if (n <= 0) return 0.0
        var acc = 0.0
        var i = 0
        while (i + 1 < pcm16le.size) {
            val sample = (pcm16le[i].toInt() and 0xFF) or (pcm16le[i + 1].toInt() shl 8)
            val v = sample.toShort().toInt()
            acc += v.toDouble() * v
            i += 2
        }
        return sqrt(acc / n)
    }

    fun downsample(pcm: ShortArray, points: Int = 8): FloatArray {
        if (pcm.isEmpty() || points <= 0) return floatArrayOf()
        val out = FloatArray(points)
        val step = pcm.size / points
        if (step <= 0) {
            out[0] = pcm[0] / 32768f
            return out
        }
        for (o in 0 until points) {
            val start = o * step
            val end = minOf(start + step, pcm.size)
            var sum = 0
            for (i in start until end) sum += pcm[i]
            out[o] = (sum / (end - start).toFloat()) / 32768f
        }
        return out
    }

    fun downsampleBytes(pcm16le: ByteArray, points: Int = 8): FloatArray {
        val n = pcm16le.size / 2
        if (n <= 0) return floatArrayOf()
        val shorts = ShortArray(n)
        var i = 0
        var s = 0
        while (i + 1 < pcm16le.size) {
            val sample = (pcm16le[i].toInt() and 0xFF) or (pcm16le[i + 1].toInt() shl 8)
            shorts[s++] = sample.toShort()
            i += 2
        }
        return downsample(shorts, points)
    }
}
