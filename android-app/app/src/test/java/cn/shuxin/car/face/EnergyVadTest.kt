package cn.shuxin.car.face

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class EnergyVadTest {
    @Test
    fun silenceNeverEndsUtterance() {
        val vad = EnergyVad()
        repeat(40) {
            assertEquals(EnergyVad.Event.NONE, vad.onRms(200.0))
        }
    }

    @Test
    fun defaultHangoverEndsNearGrokPause() {
        val vad = EnergyVad()
        repeat(4) { vad.onRms(200.0) }
        repeat(8) { vad.onRms(4000.0) }
        var endedAt = -1
        repeat(20) { index ->
            if (vad.onRms(200.0) == EnergyVad.Event.SPEECH_END && endedAt < 0) {
                endedAt = index + 1
            }
        }
        assertEquals(12, endedAt)
    }

    @Test
    fun speechThenSilenceEnds() {
        val vad = EnergyVad(startFrames = 2, endSilenceFrames = 3, minSpeechFrames = 3, floor = 100.0)
        repeat(4) { vad.onRms(80.0) }
        var sawStart = false
        repeat(6) {
            val event = vad.onRms(4000.0)
            if (event == EnergyVad.Event.SPEECH_START) sawStart = true
        }
        assertTrue(sawStart)
        var ended = false
        repeat(6) {
            if (vad.onRms(80.0) == EnergyVad.Event.SPEECH_END) ended = true
        }
        assertTrue(ended)
    }
}
