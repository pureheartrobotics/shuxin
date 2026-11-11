package cn.shuxin.car.face

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import cn.shuxin.car.R
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

class CharacterFaceView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {
    enum class Expression {
        SLEEP, IDLE, LISTEN, THINK, SPEAK, HAPPY, SAD, SURPRISE, SHY,
    }

    var expression: Expression = Expression.IDLE
        set(value) {
            if (field == value) return
            field = value
            startReaction()
            postInvalidateOnAnimation()
        }

    private val head: Bitmap = BitmapFactory.decodeResource(resources, R.drawable.face_character)
    private val src = Rect(0, 0, head.width, head.height)
    private val dst = RectF()
    private val bmpPaint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
    private val shadow = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0x220C2A4A }
    private val spark = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xCC7CF2FF.toInt() }

    private var phase = 0f
    private var trickWait = 90
    private var trickKind = 0
    private var trickT = 0f
    private var reactT = 1f
    private val sparks = Array(8) { Spark() }

    init {
        setLayerType(LAYER_TYPE_HARDWARE, null)
    }

    override fun onDraw(canvas: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return
        val size = min(w, h) * 0.78f
        val cx = w * 0.5f
        val cy = h * 0.48f
        val motion = pose()

        val shadowW = size * (0.34f + motion.squashX * 0.04f) * (1f - motion.lift * 0.45f)
        val shadowH = size * 0.07f * (1f - motion.lift * 0.5f)
        shadow.alpha = (28 + (1f - motion.lift) * 22).toInt().coerceIn(12, 56)
        canvas.drawOval(cx - shadowW, h * 0.86f - shadowH, cx + shadowW, h * 0.86f + shadowH, shadow)

        canvas.save()
        canvas.translate(cx + motion.x, cy + motion.y)
        canvas.rotate(motion.tilt)
        canvas.scale(motion.squashX, motion.squashY)
        dst.set(-size / 2f, -size / 2f, size / 2f, size / 2f)
        canvas.drawBitmap(head, src, dst, bmpPaint)
        canvas.restore()

        drawSparks(canvas, cx, cy, size, motion)
        step()
        postInvalidateOnAnimation()
    }

    private fun pose(): Pose {
        val sleep = expression == Expression.SLEEP
        val speak = expression == Expression.SPEAK || expression == Expression.HAPPY
        val think = expression == Expression.THINK
        val listen = expression == Expression.LISTEN
        val shy = expression == Expression.SHY
        val sad = expression == Expression.SAD
        val surprise = expression == Expression.SURPRISE

        val breath = if (sleep) 0.35f else 1f
        val bob = sin(phase * if (speak) 2.4f else 1.05f)
        val sway = sin(phase * 0.62f + 0.7f)
        val inhale = sin(phase * 0.9f)

        var x = sway * 10f
        var y = bob * (if (speak) 10f else 7f) * breath
        var tilt = sway * (if (think) 10f else 4.2f)
        var squashX = 1f + inhale * 0.018f
        var squashY = 1f - inhale * 0.022f
        var lift = 0f

        when {
            sleep -> {
                y += 10f
                tilt = -8f + sway * 1.6f
                squashX = 1.03f
                squashY = 0.96f
            }
            think -> {
                y -= 8f
                tilt = 12f + sway * 3f
                x += 6f
            }
            listen -> {
                y -= 4f
                squashX = 1f + inhale * 0.01f
                squashY = 1.02f - inhale * 0.012f
            }
            shy -> {
                tilt = -14f + sway * 2f
                x -= 8f
                y += 4f
            }
            sad -> {
                y += 8f
                tilt = -6f
                squashY = 0.97f
            }
            surprise -> {
                squashX = 0.94f
                squashY = 1.08f
                y -= 12f
            }
        }

        if (trickT in 0f..1f && !sleep) {
            val t = trickT
            when (trickKind) {
                1 -> {
                    val hop = sin(t * Math.PI.toFloat())
                    y -= hop * 22f
                    lift = hop
                    squashX = 1f + (1f - hop) * 0.06f
                    squashY = 1f - (1f - hop) * 0.07f
                }
                2 -> tilt += sin(t * Math.PI.toFloat()) * 16f
                3 -> {
                    x += sin(t * Math.PI.toFloat() * 2f) * 14f
                    tilt += cos(t * Math.PI.toFloat() * 2f) * 8f
                }
                4 -> {
                    squashX = 1f + sin(t * Math.PI.toFloat()) * 0.08f
                    squashY = 1f - sin(t * Math.PI.toFloat()) * 0.08f
                }
            }
        }

        if (reactT < 1f) {
            val pop = sin(reactT * Math.PI.toFloat())
            squashX += pop * 0.05f
            squashY -= pop * 0.04f
            y -= pop * 8f
        }
        return Pose(x, y, tilt, squashX, squashY, lift)
    }

    private fun drawSparks(canvas: Canvas, cx: Float, cy: Float, size: Float, motion: Pose) {
        if (expression == Expression.SLEEP) return
        val lively = expression == Expression.SPEAK || expression == Expression.HAPPY || expression == Expression.LISTEN
        for (item in sparks) {
            if (item.life <= 0f) {
                if (lively && (phase.toInt() + item.slot) % 18 == 0) item.respawn(size)
                continue
            }
            item.life -= 0.018f
            item.y -= 1.4f
            item.x += item.drift
            spark.alpha = (item.life * 180).toInt().coerceIn(0, 180)
            val r = 2.2f + (1f - item.life) * 1.6f
            canvas.drawCircle(cx + motion.x + item.x, cy + motion.y + item.y, r, spark)
        }
    }

    private fun step() {
        val speed = when (expression) {
            Expression.SLEEP -> 0.028f
            Expression.SPEAK, Expression.HAPPY -> 0.07f
            Expression.LISTEN -> 0.06f
            else -> 0.05f
        }
        phase += speed
        if (reactT < 1f) reactT += 0.045f
        if (trickT <= 1f) {
            trickT += 0.028f
        } else {
            trickWait--
            if (trickWait <= 0 && expression != Expression.SLEEP) {
                trickKind = 1 + (phase.toInt() % 4)
                trickT = 0f
                trickWait = 70 + (phase.toInt() % 110)
                if (expression == Expression.HAPPY || expression == Expression.SPEAK) {
                    trickKind = 1
                    trickWait = 40
                }
            }
        }
    }

    private fun startReaction() {
        reactT = 0f
        trickT = 0f
        trickKind = when (expression) {
            Expression.HAPPY, Expression.SPEAK -> 1
            Expression.THINK, Expression.SHY -> 2
            Expression.SURPRISE -> 4
            else -> 3
        }
        trickWait = 50
    }

    private data class Pose(
        val x: Float,
        val y: Float,
        val tilt: Float,
        val squashX: Float,
        val squashY: Float,
        val lift: Float,
    )

    private class Spark {
        var x = 0f
        var y = 0f
        var drift = 0f
        var life = 0f
        var slot = 0

        init {
            slot = hashCode() and 31
        }

        fun respawn(size: Float) {
            x = (size * 0.18f) * if (slot % 2 == 0) 1f else -1f
            y = -size * 0.12f
            drift = if (slot % 2 == 0) 0.4f else -0.4f
            life = 1f
        }
    }

    companion object {
        fun fromScene(state: FaceController.State): Expression = when (state) {
            FaceController.State.SLEEP -> Expression.SLEEP
            FaceController.State.LISTENING -> Expression.LISTEN
            FaceController.State.THINKING -> Expression.THINK
            FaceController.State.SPEAKING -> Expression.SPEAK
        }

        fun fromText(text: String, fallback: Expression): Expression {
            val t = text.trim()
            if (t.isEmpty()) return fallback
            return when {
                t.contains(Regex("开心|哈哈|太好|喜欢你|爱你|真棒|好耶")) -> Expression.HAPPY
                t.contains(Regex("难过|抱歉|对不起|心疼|没事吧|哭")) -> Expression.SAD
                t.contains(Regex("害羞|不好意思")) -> Expression.SHY
                t.contains(Regex("什么\\?|什么？|咦|哇")) -> Expression.SURPRISE
                else -> fallback
            }
        }
    }
}
