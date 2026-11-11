package cn.shuxin.car.face

/** ASR often emits a lone 嗯/啊 when the mic only heard a fan or hiss. */
object FillerSpeech {
    private val fillerOnly = Regex("^[啊阿嗯唔呃哦噢喔呀哈哼唉哎欸额恩姆呣\\s。．.，,！!？?、]+$")
    private val marks = Regex("[\\s。．.，,！!？?、]+")

    fun isFiller(text: String): Boolean {
        val trimmed = text.trim()
        if (trimmed.isEmpty() || trimmed == "—" || trimmed == "…") return true
        val compact = marks.replace(trimmed, "")
        if (compact.isEmpty()) return true
        return fillerOnly.matches(trimmed)
    }
}
