package io.github.nanomuse.hands;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.content.Intent;
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
        view.setContentDescription("Fixture task " + getTaskId());
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
        Button flatButton = new Button(this);
        flatButton.setText("Flat window");
        flatButton.setOnClickListener(v -> {
            Dialog dialog = new Dialog(this);
            TextView flat = new TextView(this);
            flat.setBackgroundColor(Color.GRAY);
            flat.setContentDescription("Flat surface");
            dialog.setContentView(flat);
            dialog.getWindow().setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(Color.GRAY));
            dialog.getWindow().setElevation(28f);
            dialog.getWindow().setWindowAnimations(0);
            dialog.show();
            dialog.getWindow().setLayout(360, 440);
        });
        content.addView(flatButton, new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.RIGHT));
        Button nativeButton = new Button(this);
        nativeButton.setText("Standard alert");
        nativeButton.setOnClickListener(v -> {
            AlertDialog alert = new AlertDialog.Builder(this)
                .setTitle("Review draft")
                .setMessage("The draft is ready. Open it here to read the latest changes.")
                .setNegativeButton("Later", null)
                .setPositiveButton("Read draft", (d, which) -> view.setText("Draft opened"))
                .create();
            alert.getWindow().setElevation(28f);
            alert.getWindow().setWindowAnimations(0);
            alert.show();
        });
        content.addView(nativeButton, new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.LEFT));
        Button next = new Button(this);
        next.setText("Next page");
        next.setOnClickListener(v -> startActivity(new Intent(this, Details.class)));
        content.addView(next, new FrameLayout.LayoutParams(-2, -2, Gravity.CENTER_HORIZONTAL | Gravity.BOTTOM));
        setContentView(content);
        // The primary-screen refusal test restores the previous app even if its runner exits.
        if (id == Display.DEFAULT_DISPLAY) view.postDelayed(this::finishAndRemoveTask, 8_000);
    }

    public static final class Details extends Activity {
        @Override public void onCreate(Bundle state) {
            super.onCreate(state);
            TextView details = new TextView(this);
            details.setText("Second activity");
            details.setBackgroundColor(Color.MAGENTA);
            setContentView(details);
        }
    }

    private void showMovingWindow(boolean raised) {
        Dialog dialog = new Dialog(this);
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        Button move = new Button(this);
        move.setText("Move dialog");
        if (raised) move.setBackgroundColor(Color.RED);
        move.setOnClickListener(v -> {
            WindowManager.LayoutParams params = dialog.getWindow().getAttributes();
            params.x += 80;
            dialog.getWindow().setAttributes(params);
        });
        panel.addView(move);
        Button password = new Button(this);
        password.setText("Change form");
        if (raised) password.setBackgroundColor(Color.CYAN);
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
