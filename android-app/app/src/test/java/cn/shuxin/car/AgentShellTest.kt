package cn.shuxin.car

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentShellTest {
    @Test
    fun recognizesBootActions() {
        assertTrue(AgentShell.isBootAction("android.intent.action.BOOT_COMPLETED"))
        assertTrue(AgentShell.isBootAction("android.intent.action.LOCKED_BOOT_COMPLETED"))
        assertTrue(AgentShell.isBootAction("android.intent.action.QUICKBOOT_POWERON"))
        assertTrue(AgentShell.isBootAction("android.intent.action.USER_UNLOCKED"))
    }

    @Test
    fun ignoresOtherActions() {
        assertFalse(AgentShell.isBootAction(null))
        assertFalse(AgentShell.isBootAction(""))
        assertFalse(AgentShell.isBootAction("android.intent.action.USER_PRESENT"))
        assertFalse(AgentShell.isBootAction("android.intent.action.MAIN"))
    }

    @Test
    fun kioskComponentNames() {
        assertTrue(AgentShell.ADMIN_COMPONENT.startsWith("cn.shuxin.car/"))
        assertTrue(AgentShell.HOME_COMPONENT.startsWith("cn.shuxin.car/"))
    }
}
