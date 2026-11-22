package io.github.nanomuse.hands;

import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Display;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.TextView;

/** A standalone target in the instrumentation APK. It never opens another app or the network. */
public final class HandsDisplayFixture extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (Build.VERSION.SDK_INT < 34) {
            finish();
            return;
        }
        int id = getDisplay().getDisplayId();
        TextView view = new TextView(this);
        view.setGravity(Gravity.TOP);
        view.setText("Ready on display " + id);
        view.setBackgroundColor(Color.GREEN);
        view.setOnClickListener(v -> {
            view.setText("Tapped on display " + id);
            view.setBackgroundColor(Color.BLUE);
        });
        view.setOnLongClickListener(v -> {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
            return true;
        });
        setContentView(view);
        // The primary-screen refusal test restores the previous app even if its runner exits.
        if (id == Display.DEFAULT_DISPLAY) view.postDelayed(this::finishAndRemoveTask, 8_000);
    }
}
