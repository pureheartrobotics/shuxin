package cn.shuxin.car

import android.app.Activity
import android.app.ActivityManager
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.UserManager
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/** Dedicated-device shell: HOME, immersive bars, device-owner lock-task. */
object AgentShell {
    const val ACTION_BOOT = "android.intent.action.BOOT_COMPLETED"
    const val ACTION_LOCKED_BOOT = "android.intent.action.LOCKED_BOOT_COMPLETED"
    const val ACTION_USER_UNLOCKED = "android.intent.action.USER_UNLOCKED"
    const val ACTION_QUICKBOOT = "android.intent.action.QUICKBOOT_POWERON"
    const val ADMIN_COMPONENT = "cn.shuxin.car/.KioskAdminReceiver"
    const val HOME_COMPONENT = "cn.shuxin.car/.MainActivity"

    fun isBootAction(action: String?): Boolean {
        return action == ACTION_BOOT ||
            action == ACTION_LOCKED_BOOT ||
            action == ACTION_USER_UNLOCKED ||
            action == ACTION_QUICKBOOT
    }

    fun adminComponent(context: Context): ComponentName {
        return ComponentName(context, KioskAdminReceiver::class.java)
    }

    fun launchIntent(context: Context): Intent {
        return Intent(context, MainActivity::class.java)
            .addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_CLEAR_TOP or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP or
                    Intent.FLAG_ACTIVITY_REORDER_TO_FRONT,
            )
    }

    fun hideSystemBars(activity: Activity) {
        WindowCompat.setDecorFitsSystemWindows(activity.window, false)
        val controller = WindowInsetsControllerCompat(activity.window, activity.window.decorView)
        controller.hide(WindowInsetsCompat.Type.systemBars())
        controller.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
    }

    fun watchInsets(activity: Activity) {
        val decor = activity.window.decorView
        ViewCompat.setOnApplyWindowInsetsListener(decor) { view, insets ->
            if (insets.isVisible(WindowInsetsCompat.Type.systemBars())) {
                view.post { hideSystemBars(activity) }
            }
            insets
        }
    }

    fun applyOwnerKiosk(activity: Activity) {
        val dpm = activity.getSystemService(DevicePolicyManager::class.java) ?: return
        if (!dpm.isDeviceOwnerApp(activity.packageName)) {
            startLockTaskIfAllowed(activity)
            return
        }
        val admin = adminComponent(activity)
        runCatching { dpm.setLockTaskPackages(admin, arrayOf(activity.packageName)) }
        if (Build.VERSION.SDK_INT >= 28) {
            runCatching {
                dpm.setLockTaskFeatures(admin, DevicePolicyManager.LOCK_TASK_FEATURE_NONE)
            }
        }
        val home = IntentFilter(Intent.ACTION_MAIN).apply {
            addCategory(Intent.CATEGORY_HOME)
            addCategory(Intent.CATEGORY_DEFAULT)
        }
        runCatching {
            dpm.addPersistentPreferredActivity(
                admin,
                home,
                ComponentName(activity, MainActivity::class.java),
            )
        }
        runCatching { dpm.setKeyguardDisabled(admin, true) }
        runCatching { dpm.setStatusBarDisabled(admin, true) }
        runCatching { dpm.addUserRestriction(admin, UserManager.DISALLOW_SAFE_BOOT) }
        runCatching { dpm.addUserRestriction(admin, UserManager.DISALLOW_ADD_USER) }
        startLockTaskIfAllowed(activity)
    }

    fun startLockTaskIfAllowed(activity: Activity) {
        val dpm = activity.getSystemService(DevicePolicyManager::class.java) ?: return
        if (!dpm.isLockTaskPermitted(activity.packageName)) return
        if (lockTaskActive(activity)) return
        runCatching { activity.startLockTask() }
    }

    fun lockTaskActive(activity: Activity): Boolean {
        val am = activity.getSystemService(ActivityManager::class.java) ?: return false
        return am.lockTaskModeState != ActivityManager.LOCK_TASK_MODE_NONE
    }
}
