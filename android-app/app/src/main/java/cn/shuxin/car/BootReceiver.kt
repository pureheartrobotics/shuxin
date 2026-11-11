package cn.shuxin.car

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (!AgentShell.isBootAction(intent.action)) return
        runCatching { context.startActivity(AgentShell.launchIntent(context)) }
    }
}
