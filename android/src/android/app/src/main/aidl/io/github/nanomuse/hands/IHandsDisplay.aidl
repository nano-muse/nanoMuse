package io.github.nanomuse.hands;

import android.view.Surface;

interface IHandsDisplay {
    // Reserved by Shizuku for service teardown.
    void destroy() = 16777114;
    // Returns the display ID and the Android user ID of the calling nanoMuse app.
    int[] open(in Surface surface, int width, int height, int dpi, IBinder owner) = 1;
    void close() = 2;
}
