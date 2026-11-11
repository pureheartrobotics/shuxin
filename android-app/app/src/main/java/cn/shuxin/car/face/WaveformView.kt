package cn.shuxin.car.face

import android.content.Context
import android.graphics.Canvas
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View

class WaveformView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {
    enum class Mode { SLEEP, IDLE, LISTEN, THINK, SPEAK }

    init {
        isClickable = true
        isFocusable = true
        setBackgroundColor(0xFFFFFFFF.toInt())
    }

    @Volatile
    var mode: Mode = Mode.SLEEP

    fun push(samples: FloatArray) {
        // Face motion is owned by CharacterFaceView; keep this as the tap layer.
    }

    fun flatten() = Unit

    override fun onTouchEvent(event: MotionEvent): Boolean {
        super.onTouchEvent(event)
        return true
    }

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(0xFFFFFFFF.toInt())
    }
}
