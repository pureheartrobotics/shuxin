package cn.shuxin.car.face

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CompanionIntentsTest {
    @Test
    fun weatherWithCity() {
        val intent = CompanionIntents.parse("上海今天天气怎么样")
        assertTrue(intent is CompanionIntent.Weather)
        assertEquals("上海", (intent as CompanionIntent.Weather).city)
    }

    @Test
    fun weatherWithoutCity() {
        val intent = CompanionIntents.parse("现在天气怎么样")
        assertTrue(intent is CompanionIntent.Weather)
        assertNull((intent as CompanionIntent.Weather).city)
    }

    @Test
    fun weatherUmbrella() {
        val intent = CompanionIntents.parse("明天带伞吗")
        assertTrue(intent is CompanionIntent.Weather)
    }

    @Test
    fun timerMinutes() {
        val intent = CompanionIntents.parse("三分钟以后叫我")
        assertEquals(180, (intent as CompanionIntent.Timer).seconds)
    }

    @Test
    fun timerHalfHour() {
        val intent = CompanionIntents.parse("定个半小时")
        assertEquals(1800, (intent as CompanionIntent.Timer).seconds)
    }

    @Test
    fun memo() {
        val intent = CompanionIntents.parse("记住明天买牛奶")
        assertEquals("明天买牛奶", (intent as CompanionIntent.Memo).text)
        assertNull(CompanionIntents.parse("记下了"))
        assertNull(CompanionIntents.parse("记住了"))
        assertNull(CompanionIntents.parse("你好初心"))
    }

    @Test
    fun reminderWithoutDurationIsNotMemo() {
        assertNull(CompanionIntents.parse("提醒我明天开会"))
        assertNull(CompanionIntents.parse("你好啊"))
        assertNull(CompanionIntents.parse("今天过得怎么样"))
    }

    @Test
    fun ignoreChassis() {
        assertNull(CompanionIntents.parse("往前走一点"))
    }

    @Test
    fun look() {
        assertEquals(CompanionIntent.Look, CompanionIntents.parse("看看这是什么"))
        assertEquals(CompanionIntent.Look, CompanionIntents.parse("前面有什么"))
        assertEquals(CompanionIntent.Look, CompanionIntents.parse("你能看见吗"))
        assertEquals(CompanionIntent.Look, CompanionIntents.parse("摄像头接上了吗"))
        assertTrue(CompanionIntents.parse("今天天气怎么样") is CompanionIntent.Weather)
    }

    @Test
    fun lookAroundPhotoAlbumAndHead() {
        assertEquals(CompanionIntent.LookAround, CompanionIntents.parse("你看到什么"))
        assertEquals(CompanionIntent.LookAround, CompanionIntents.parse("环顾四周看看"))
        assertEquals(CompanionIntent.Photo, CompanionIntents.parse("拍一张"))
        assertEquals(CompanionIntent.Album, CompanionIntents.parse("打开相册"))
        assertEquals(CompanionIntent.Nod, CompanionIntents.parse("点点头"))
        assertEquals(CompanionIntent.Shake, CompanionIntents.parse("摇摇头"))
        assertTrue(CompanionIntents.isHermesBody(CompanionIntent.LookAround))
        assertTrue(CompanionIntents.isHermesBody(CompanionIntent.Nod))
        assertTrue(!CompanionIntents.isHermesBody(CompanionIntent.Weather(null)))
    }
}
