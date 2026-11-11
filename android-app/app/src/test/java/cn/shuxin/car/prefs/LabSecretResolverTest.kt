package cn.shuxin.car.prefs

import org.junit.Assert.assertEquals
import org.junit.Test

class LabSecretResolverTest {
    @Test
    fun pinMapsToStoredSecret() {
        val table = mapOf("SX-000003" to "long-cloud-secret")
        assertEquals(
            "long-cloud-secret",
            LabSecretResolver.resolve("SX-000003", "k11c", table),
        )
        assertEquals(
            "long-cloud-secret",
            LabSecretResolver.resolve("SX-000003", " K11C ", table),
        )
    }

    @Test
    fun unknownDeviceKeepsTypedPin() {
        assertEquals(
            "k11c",
            LabSecretResolver.resolve("SX-000099", "k11c", emptyMap()),
        )
    }

    @Test
    fun pastedFullSecretPassesThrough() {
        assertEquals(
            "already-full-secret",
            LabSecretResolver.resolve(
                "SX-000003",
                "already-full-secret",
                mapOf("SX-000003" to "mapped"),
            ),
        )
    }
}
