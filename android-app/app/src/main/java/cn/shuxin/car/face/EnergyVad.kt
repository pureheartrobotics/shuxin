package cn.shuxin.car.face

/** 60ms frames. Hangover 12 ≈ 720ms. Sensitive enough to catch real speech. */
class EnergyVad(
    private val startFrames: Int = 3,
    private val endSilenceFrames: Int = 12,
    private val minSpeechFrames: Int = 5,
    private val floor: Double = 900.0,
) {
    enum class Event { NONE, SPEECH_START, SPEECH_END }

    private var noise = floor
    private var calibrated = 0
    private var voiced = false
    private var voicedFrames = 0
    private var silence = 0

    fun reset() {
        noise = floor
        calibrated = 0
        voiced = false
        voicedFrames = 0
        silence = 0
    }

    fun onRms(rms: Double): Event {
        if (calibrated < 4) {
            noise = if (calibrated == 0) rms else noise * 0.7 + rms * 0.3
            calibrated++
            return Event.NONE
        }
        // Additive margin: a fan in the first frames must not raise the bar so high
        // that real speech never counts as speech.
        val threshold = maxOf(floor + 400.0, noise + 1000.0)
        if (rms < noise) {
            noise = noise * 0.95 + rms * 0.05
        }
        val speech = rms > threshold
        if (!voiced) {
            if (speech) {
                voicedFrames++
                if (voicedFrames >= startFrames) {
                    voiced = true
                    silence = 0
                    return Event.SPEECH_START
                }
            } else {
                voicedFrames = 0
            }
            return Event.NONE
        }
        if (speech) {
            voicedFrames++
            silence = 0
            return Event.NONE
        }
        silence++
        if (voicedFrames >= minSpeechFrames && silence >= endSilenceFrames) {
            voiced = false
            voicedFrames = 0
            silence = 0
            return Event.SPEECH_END
        }
        return Event.NONE
    }
}
