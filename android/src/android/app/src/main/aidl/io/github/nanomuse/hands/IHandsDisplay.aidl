package io.github.nanomuse.hands;

import android.view.Surface;

interface IHandsDisplay {
    // Reserved by Shizuku for service teardown.
    void destroy() = 16777114;
    // Returns the display ID and the Android user ID of the calling nanoMuse app.
    int[] open(in Surface surface, int width, int height, int dpi, IBinder owner) = 1;
    void close() = 2;
    // Pin the launched app's only task. The only possible destination is the phone itself.
    boolean rememberTask(String packageName) = 3;
    boolean handOffToPhone() = 4;
    // No caller-supplied command, component, user, task or display ID.
    boolean launchPackage(String packageName) = 5;
    boolean tap(int x, int y) = 6;
    boolean swipe(int x1, int y1, int x2, int y2, int durationMs) = 7;
    boolean back() = 8;
    int[] identity() = 9;
}
