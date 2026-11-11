package cn.shuxin.car.camera

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.io.path.createTempDirectory

class PhotoAlbumTest {
    @Test
    fun savesAndListsNewestFirst() {
        val dir = createTempDirectory("sx-album").toFile()
        try {
            val album = PhotoAlbum(dir)
            val first = album.save(byteArrayOf(1, 2, 3))
            first.setLastModified(1_000L)
            val second = album.save(byteArrayOf(4, 5, 6))
            second.setLastModified(2_000L)
            val latest = album.latest(2)
            assertEquals(2, latest.size)
            assertEquals(second.name, latest[0].name)
            assertTrue(latest[0].readBytes().contentEquals(byteArrayOf(4, 5, 6)))
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test
    fun prunesOldPhotos() {
        val dir = createTempDirectory("sx-album-prune").toFile()
        try {
            val album = PhotoAlbum(dir)
            repeat(PhotoAlbum.KEEP + 3) { index ->
                File(dir, "sx-$index.jpg").writeBytes(byteArrayOf(index.toByte()))
            }
            album.save(byteArrayOf(9))
            assertEquals(PhotoAlbum.KEEP, album.latest(100).size)
        } finally {
            dir.deleteRecursively()
        }
    }
}
