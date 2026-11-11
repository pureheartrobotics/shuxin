package cn.shuxin.car.camera

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.ImageFormat
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.util.Log
import android.view.Surface
import android.view.TextureView
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class CameraCapture(
    context: Context,
    private val previewView: TextureView? = null,
) {
    private val app = context.applicationContext
    private val manager = app.getSystemService(Context.CAMERA_SERVICE) as CameraManager
    private val main = Handler(Looper.getMainLooper())
    private val busy = AtomicBoolean(false)

    fun capture(onDone: (ByteArray?) -> Unit) {
        if (!busy.compareAndSet(false, true)) {
            Log.w(TAG, "capture skipped: busy")
            return
        }
        val start = Runnable {
            Thread({
                val jpeg = runCatching { captureBlocking() }
                    .onFailure { Log.e(TAG, "capture failed", it) }
                    .getOrNull()
                Log.i(TAG, "capture done bytes=${jpeg?.size ?: 0}")
                busy.set(false)
                main.post { onDone(jpeg) }
            }, "camera-still").start()
        }
        val view = previewView
        if (view != null && !view.isAvailable) {
            main.postDelayed(start, 450)
        } else {
            start.run()
        }
    }

    @SuppressLint("MissingPermission")
    private fun captureBlocking(): ByteArray? {
        val cameraId = pickCamera()
        if (cameraId == null) {
            Log.w(TAG, "no camera id")
            return null
        }
        Log.i(TAG, "open camera id=$cameraId")
        val thread = HandlerThread("camera2-still").also { it.start() }
        val handler = Handler(thread.looper)
        val size = jpegSize(cameraId)
        val reader = ImageReader.newInstance(size.first, size.second, ImageFormat.JPEG, 2)
        val dummyTexture = SurfaceTexture(1).also { it.setDefaultBufferSize(size.first, size.second) }
        val previewSurface = previewSurface(dummyTexture)
        val jpegReady = CountDownLatch(1)
        var jpeg: ByteArray? = null
        reader.setOnImageAvailableListener(
            { r ->
                val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
                image.use {
                    val buffer = it.planes[0].buffer
                    val bytes = ByteArray(buffer.remaining())
                    buffer.get(bytes)
                    jpeg = bytes
                }
                jpegReady.countDown()
            },
            handler,
        )
        val opened = CountDownLatch(1)
        var device: CameraDevice? = null
        val sessionReady = CountDownLatch(1)
        var session: CameraCaptureSession? = null
        try {
            manager.openCamera(
                cameraId,
                object : CameraDevice.StateCallback() {
                    override fun onOpened(camera: CameraDevice) {
                        device = camera
                        opened.countDown()
                    }
                    override fun onDisconnected(camera: CameraDevice) {
                        Log.w(TAG, "disconnected")
                        camera.close()
                        opened.countDown()
                    }
                    override fun onError(camera: CameraDevice, error: Int) {
                        Log.e(TAG, "open error=$error")
                        camera.close()
                        opened.countDown()
                    }
                },
                handler,
            )
            if (!opened.await(4, TimeUnit.SECONDS) || device == null) {
                Log.w(TAG, "open timeout")
                return null
            }
            val cam = device!!
            val targets = listOf(previewSurface, reader.surface)
            cam.createCaptureSession(
                targets,
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(value: CameraCaptureSession) {
                        session = value
                        sessionReady.countDown()
                    }
                    override fun onConfigureFailed(value: CameraCaptureSession) {
                        Log.e(TAG, "session configure failed")
                        sessionReady.countDown()
                    }
                },
                handler,
            )
            if (!sessionReady.await(4, TimeUnit.SECONDS) || session == null) {
                Log.w(TAG, "session timeout")
                return null
            }
            val previewReq = cam.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(previewSurface)
                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
                set(CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_ON)
            }.build()
            session!!.setRepeatingRequest(previewReq, null, handler)
            Thread.sleep(450)
            val still = cam.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                addTarget(reader.surface)
                set(CaptureRequest.JPEG_QUALITY, 70.toByte())
            }.build()
            session!!.capture(still, null, handler)
            if (!jpegReady.await(4, TimeUnit.SECONDS)) {
                Log.w(TAG, "jpeg timeout")
            }
            return shrink(jpeg)
        } finally {
            runCatching { session?.close() }
            runCatching { device?.close() }
            runCatching { reader.close() }
            dummyTexture.release()
            thread.quitSafely()
        }
    }

    private fun previewSurface(fallback: SurfaceTexture): Surface {
        val view = previewView
        val texture = view?.surfaceTexture
        if (view != null && view.isAvailable && texture != null) {
            texture.setDefaultBufferSize(640, 480)
            return Surface(texture)
        }
        return Surface(fallback)
    }

    private fun pickCamera(): String? {
        val ids = manager.cameraIdList
        Log.i(TAG, "cameras=${ids.joinToString()}")
        if (ids.isEmpty()) return null
        return ids.firstOrNull { id ->
            val facing = manager.getCameraCharacteristics(id)
                .get(CameraCharacteristics.LENS_FACING)
            facing == CameraCharacteristics.LENS_FACING_BACK
        } ?: ids.first()
    }

    private fun jpegSize(cameraId: String): Pair<Int, Int> {
        val stream = manager.getCameraCharacteristics(cameraId)
            .get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?: return 640 to 480
        val jpeg = stream.getOutputSizes(ImageFormat.JPEG)?.toList().orEmpty()
        val picked = jpeg.firstOrNull { it.width <= 1280 && it.height <= 960 }
            ?: jpeg.minByOrNull { it.width * it.height }
        return if (picked == null) 640 to 480 else picked.width to picked.height
    }

    private fun shrink(jpeg: ByteArray?): ByteArray? {
        if (jpeg == null || jpeg.size <= 180_000) return jpeg
        val bitmap = android.graphics.BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: return jpeg
        val out = ByteArrayOutputStream()
        bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 58, out)
        bitmap.recycle()
        return out.toByteArray()
    }

    companion object {
        private const val TAG = "ShuxinCamera"
    }
}
