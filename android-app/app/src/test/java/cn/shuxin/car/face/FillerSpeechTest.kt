package cn.shuxin.car.face

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FillerSpeechTest {
    @Test
    fun noiseFillers() {
        assertTrue(FillerSpeech.isFiller("嗯"))
        assertTrue(FillerSpeech.isFiller("嗯。"))
        assertTrue(FillerSpeech.isFiller("啊"))
        assertTrue(FillerSpeech.isFiller("哦"))
        assertTrue(FillerSpeech.isFiller("嗯嗯"))
        assertTrue(FillerSpeech.isFiller("   "))
    }

    @Test
    fun realSpeechKept() {
        assertFalse(FillerSpeech.isFiller("你好"))
        assertFalse(FillerSpeech.isFiller("嗯，好的"))
        assertFalse(FillerSpeech.isFiller("几点了"))
        assertFalse(FillerSpeech.isFiller("喂"))
        assertFalse(FillerSpeech.isFiller("停"))
    }
}
