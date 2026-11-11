package cn.shuxin.car.face

import org.junit.Assert.assertEquals
import org.junit.Test

class CharacterFaceViewTest {
    @Test
    fun textPicksMood() {
        val speak = CharacterFaceView.Expression.SPEAK
        assertEquals(CharacterFaceView.Expression.HAPPY, CharacterFaceView.fromText("太好了哈哈", speak))
        assertEquals(CharacterFaceView.Expression.SAD, CharacterFaceView.fromText("抱歉，你没事吧", speak))
        assertEquals(CharacterFaceView.Expression.SURPRISE, CharacterFaceView.fromText("咦，什么？", speak))
        assertEquals(speak, CharacterFaceView.fromText("现在几点了", speak))
    }
}
