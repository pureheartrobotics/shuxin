package cn.shuxin.car.motor

interface MotorLink {
    val ready: Boolean
    fun start()
    fun stopLink()
    fun setMotor(left: Int, right: Int, durationMs: Int)
    fun emergencyStop()
    fun sendCommand(line: String) {}
}

class MockMotorLink(
    private val onStatus: (String) -> Unit,
) : MotorLink {
    @Volatile
    override var ready: Boolean = false
        private set

    override fun start() {
        ready = true
        onStatus("电机：模拟 / 停")
    }

    override fun stopLink() {
        ready = false
        onStatus("电机：模拟 / 未连接")
    }

    override fun setMotor(left: Int, right: Int, durationMs: Int) {
        onStatus("电机：模拟 左${left} 右${right} ${durationMs}ms")
    }

    override fun emergencyStop() {
        onStatus("电机：模拟 / 急停")
    }

    override fun sendCommand(line: String) {
        onStatus("电机：模拟 $line")
    }
}
