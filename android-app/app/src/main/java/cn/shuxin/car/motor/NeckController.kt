package cn.shuxin.car.motor

import android.os.Handler

class NeckController(
    private val motor: MotorLink,
    private val handler: Handler,
) {
    @Volatile
    private var token = 0

    fun cancel() {
        token++
    }

    fun nod() {
        motor.sendCommand("NOD")
    }

    fun shake() {
        motor.sendCommand("SHAKE")
    }

    fun center() {
        motor.sendCommand("HEAD 90 90")
    }

    fun pose(pan: Int, tilt: Int) {
        motor.sendCommand("HEAD $pan $tilt")
    }

    fun lookAround(onPose: (String) -> Unit, onDone: () -> Unit) {
        val mine = ++token
        val poses = listOf(
            Triple("center", 90, 90),
            Triple("left", 48, 90),
            Triple("right", 132, 90),
            Triple("center", 90, 90),
            Triple("up", 90, 62),
            Triple("down", 90, 118),
            Triple("center", 90, 90),
        )
        fun step(index: Int) {
            if (mine != token) return
            if (index >= poses.size) {
                onDone()
                return
            }
            val (name, pan, tilt) = poses[index]
            pose(pan, tilt)
            onPose(name)
            handler.postDelayed({ step(index + 1) }, POSE_MS)
        }
        step(0)
    }

    companion object {
        const val POSE_MS = 650L
    }
}
