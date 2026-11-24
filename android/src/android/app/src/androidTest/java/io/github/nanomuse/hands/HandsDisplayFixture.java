package io.github.nanomuse.hands;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Display;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
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
        FrameLayout content = new FrameLayout(this);
        content.addView(view);
        Button dialogButton = new Button(this);
        dialogButton.setText("Moving window");
        dialogButton.setOnClickListener(v -> showMovingWindow(false));
        content.addView(dialogButton, new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.LEFT));
        Button shadowButton = new Button(this);
        shadowButton.setText("Raised window");
        shadowButton.setOnClickListener(v -> showMovingWindow(true));
        content.addView(shadowButton, new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.RIGHT));
        setContentView(content);
        // The primary-screen refusal test restores the previous app even if its runner exits.
        if (id == Display.DEFAULT_DISPLAY) view.postDelayed(this::finishAndRemoveTask, 8_000);
    }

    private void showMovingWindow(boolean raised) {
        Dialog dialog = new Dialog(this);
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        Button move = new Button(this);
        move.setText("Move dialog");
        move.setOnClickListener(v -> {
            WindowManager.LayoutParams params = dialog.getWindow().getAttributes();
            params.x += 80;
            dialog.getWindow().setAttributes(params);
        });
        panel.addView(move);
        Button password = new Button(this);
        password.setText("Change form");
        password.setOnClickListener(v -> {
            EditText field = new EditText(this);
            field.setSingleLine(true);
            field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            panel.addView(field);
        });
        panel.addView(password);
        dialog.setContentView(panel);
        // Android computes surface insets from window elevation when it first attaches the decor.
        dialog.getWindow().setElevation(raised ? 28f : 0f);
        dialog.getWindow().setWindowAnimations(0);
        dialog.show();
        dialog.getWindow().setLayout(360, 440);
    }
}
