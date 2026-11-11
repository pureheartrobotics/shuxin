package cn.shuxin.car.camera

import java.io.File

class PhotoAlbum(private val dir: File) {
    init {
        dir.mkdirs()
    }

    fun save(jpeg: ByteArray): File {
        dir.mkdirs()
        val file = File(dir, "sx-${System.currentTimeMillis()}.jpg")
        file.writeBytes(jpeg)
        prune()
        return file
    }

    fun latest(limit: Int = 12): List<File> {
        return dir.listFiles { file -> file.isFile && file.extension.equals("jpg", ignoreCase = true) }
            ?.sortedByDescending { it.lastModified() }
            ?.take(limit)
            ?: emptyList()
    }

    private fun prune() {
        latest(100).drop(KEEP).forEach { it.delete() }
    }

    companion object {
        const val KEEP = 30
    }
}
