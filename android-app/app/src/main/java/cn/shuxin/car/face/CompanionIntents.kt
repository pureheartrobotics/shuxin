package cn.shuxin.car.face

sealed class CompanionIntent {
    data class Weather(val city: String?) : CompanionIntent()
    data class Timer(val seconds: Int) : CompanionIntent()
    data class Memo(val text: String) : CompanionIntent()
    data object RecallMemos : CompanionIntent()
    data object Shutdown : CompanionIntent()
    data object Look : CompanionIntent()
    data object LookAround : CompanionIntent()
    data object Photo : CompanionIntent()
    data object Album : CompanionIntent()
    data object Nod : CompanionIntent()
    data object Shake : CompanionIntent()
}

object CompanionIntents {
    private val CITIES = listOf(
        "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "武汉", "西安", "南京",
        "苏州", "天津", "长沙", "郑州", "青岛", "厦门", "宁波", "合肥", "福州", "济南",
        "沈阳", "大连", "哈尔滨", "昆明", "南宁", "南昌", "石家庄", "太原", "长春", "贵阳",
        "海口", "兰州", "乌鲁木齐", "拉萨", "银川", "西宁", "呼和浩特", "香港", "澳门", "台北",
        "无锡", "佛山", "东莞", "珠海", "温州", "金华", "嘉兴", "黄浦", "浦东",
    )
    private val NOT_CITY = setOf("今天", "现在", "这里", "那里", "外面", "咱们", "我们", "本地", "天气")
    private val CHASSIS = Regex("前进|后退|左转|右转|往前|往后|停车|停下|^停$|倒车")
    private val TIMER = Regex(
        """(?:定|设|倒计时|闹钟|计时|提醒我|叫我|喊我)?.{0,6}?(半|[一二三四五六七八九十两\d]+)(个)?(小时|分钟|分种|分|秒)(?:钟)?(?:以?后|之后)?(?:再?(?:叫我|提醒我|喊我|告诉我))?""",
    )
    private val WEATHER = Regex("天气|气温|下雨|下雪|冷不冷|热不热|多少度|带伞|带雨伞")
    private val MEMO_PREFIX = Regex("^(?:帮我)?(?:记住|记一下|别忘了)(?!了)(.{2,40})$")
    private val RECALL = Regex("记了什么|记过什么|我的备忘|记了哪些")
    private val SHUTDOWN = Regex("关机|关掉机器|关闭电源|请关机|^关掉$|断电")
    private val LOOK_AROUND = Regex(
        "看见什么|看到什么|看到了什么|看见了什么|你看到什么|你看见什么|" +
            "环顾|看看周围|四周看看|看看四周|周围有什么|四处看看",
    )
    private val PHOTO = Regex("拍一张|拍张照|拍个照|拍张照片|^拍照$|照相")
    private val ALBUM = Regex("相册|看看照片|打开相册|看相册|照片都有|看下相册")
    private val NOD = Regex("点头|点点头|点一下头")
    private val SHAKE = Regex("摇头|摇摇头|摇一下头")
    private val LOOK = Regex(
        "摄像头|镜头|你能看见|你能看到|看得见|看得到|看见吗|看到吗|" +
            "你看看|帮我看|你看这|看看这|看看那|看看前面|看看我|看一看|看一下|^看看$|" +
            "这是什么|那是什么|前面有什么|眼前有什么",
    )

    fun parse(raw: String): CompanionIntent? {
        val text = raw.replace("\\s+".toRegex(), "").trim()
        if (text.isEmpty() || CHASSIS.containsMatchIn(text)) return null
        if (SHUTDOWN.containsMatchIn(text)) return CompanionIntent.Shutdown
        if (NOD.containsMatchIn(text)) return CompanionIntent.Nod
        if (SHAKE.containsMatchIn(text)) return CompanionIntent.Shake
        if (ALBUM.containsMatchIn(text)) return CompanionIntent.Album
        if (PHOTO.containsMatchIn(text)) return CompanionIntent.Photo
        if (LOOK_AROUND.containsMatchIn(text) && !WEATHER.containsMatchIn(text)) return CompanionIntent.LookAround
        if (LOOK.containsMatchIn(text) && !WEATHER.containsMatchIn(text)) return CompanionIntent.Look
        TIMER.find(text)?.let { match ->
            val seconds = durationSeconds(match.groupValues[1], match.groupValues[3]) ?: return@let
            if (seconds in 5..7200) return CompanionIntent.Timer(seconds)
        }
        if (WEATHER.containsMatchIn(text)) {
            return CompanionIntent.Weather(extractCity(text))
        }
        if (RECALL.containsMatchIn(text)) return CompanionIntent.RecallMemos
        MEMO_PREFIX.find(text)?.groupValues?.getOrNull(1)?.trim('，', ',', '。', '！', '!', ' ')?.let { memo ->
            if (memo.length in 2..40) return CompanionIntent.Memo(memo)
        }
        return null
    }

    fun isHermesBody(intent: CompanionIntent): Boolean {
        return intent is CompanionIntent.Look ||
            intent is CompanionIntent.LookAround ||
            intent is CompanionIntent.Photo ||
            intent is CompanionIntent.Album ||
            intent is CompanionIntent.Nod ||
            intent is CompanionIntent.Shake
    }

    fun extractCity(text: String): String? {
        CITIES.firstOrNull { it in text }?.let { return it }
        Regex("([\u4e00-\u9fff]{2,3})(?:市|的天气)").find(text)?.groupValues?.getOrNull(1)?.let {
            if (it !in NOT_CITY) return it
        }
        return null
    }

    internal fun durationSeconds(number: String, unit: String): Int? {
        if (number == "半") {
            return when {
                unit.startsWith("小时") -> 1800
                unit.startsWith("秒") -> 30
                else -> 30
            }
        }
        val amount = parseNumber(number) ?: return null
        return when {
            unit.startsWith("小时") -> amount * 3600
            unit.startsWith("秒") -> amount
            else -> amount * 60
        }
    }

    internal fun parseNumber(raw: String): Int? {
        if (raw == "半") return 30
        raw.toIntOrNull()?.let { return it }
        val digits = mapOf(
            '零' to 0, '一' to 1, '二' to 2, '两' to 2, '三' to 3, '四' to 4,
            '五' to 5, '六' to 6, '七' to 7, '八' to 8, '九' to 9,
        )
        if (raw == "十") return 10
        if (raw.endsWith("十") && raw.length == 2) {
            val tens = digits[raw[0]] ?: return null
            return tens * 10
        }
        if (raw.startsWith("十") && raw.length == 2) {
            val ones = digits[raw[1]] ?: return null
            return 10 + ones
        }
        if (raw.length == 1) return digits[raw[0]]
        if (raw.length == 3 && raw[1] == '十') {
            val tens = digits[raw[0]] ?: return null
            val ones = digits[raw[2]] ?: return null
            return tens * 10 + ones
        }
        return null
    }
}
