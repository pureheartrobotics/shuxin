package cn.shuxin.car

import android.app.admin.DeviceAdminReceiver

/** Device-owner receiver so lock-task and HOME stick across reboot. */
class KioskAdminReceiver : DeviceAdminReceiver()
