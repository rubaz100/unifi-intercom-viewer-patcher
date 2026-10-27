package com.uvp;

import android.content.Context;
import android.content.Intent;
import android.os.Process;

import java.io.File;

/**
 * "Factory reset" from the controller (device removed): the device wipes itself
 * via the system MasterClearReceiver, which a normal app can't reach. Reset the
 * app instead: mark the reset and restart; the next start wipes the app's own
 * data (adoption, settings, cached media) before anything has opened it, so the
 * old process can't write its preferences back.
 */
public final class Reset {
    private static final String MARKER = "uvp-factory-reset";

    private Reset() {}

    /** Called instead of the MasterClearReceiver broadcast. */
    public static void run(Context ctx) {
        Context app = ctx.getApplicationContext();
        try {
            new File(app.getDataDir(), MARKER).createNewFile();
            Intent launch = app.getPackageManager().getLaunchIntentForPackage(app.getPackageName());
            if (launch != null) {
                app.startActivity(Intent.makeRestartActivityTask(launch.getComponent()));
            }
        } catch (Exception e) {
            android.util.Log.w("UVP", "reset", e);
        }
        Process.killProcess(Process.myPid());
        System.exit(0);
    }

    /** Called first thing in Application.onCreate. */
    public static void onStart(Context app) {
        try {
            if (!new File(app.getDataDir(), MARKER).exists()) return;
            android.util.Log.i("UVP", "factory reset: wiping app data");
            File ext = app.getExternalFilesDir(null);
            for (File d : new File[] {ext == null ? null : ext.getParentFile(), app.getDataDir()}) {
                File[] children = d == null ? null : d.listFiles();
                if (children == null) continue;
                for (File c : children) {
                    if (!c.getName().equals("lib")) delete(c);
                }
            }
        } catch (RuntimeException e) {
            android.util.Log.w("UVP", "reset wipe", e);
        }
    }

    private static void delete(File f) {
        File[] children = f.isDirectory() ? f.listFiles() : null;
        if (children != null) {
            for (File c : children) delete(c);
        }
        f.delete();
    }
}
