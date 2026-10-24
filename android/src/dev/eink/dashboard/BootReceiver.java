package dev.eink.dashboard;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Relaunches the dashboard after a reboot. Needs the SYSTEM_ALERT_WINDOW app-op (see setup-device.ps1). */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        Intent i = new Intent(context, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        try {
            context.startActivity(i);
        } catch (Exception ignored) {
            // background activity start denied: the user can tap the launcher icon instead
        }
    }
}
