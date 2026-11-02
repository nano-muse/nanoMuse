package io.github.nanomuse.avatar

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface

/** One cached still shared by the Compose avatar, exported cards and the hands capsule. */
object EmojiPortrait {
    private var cached: Pair<EmojiLook, Bitmap>? = null

    @Synchronized fun bitmap(look: EmojiLook): Bitmap {
        cached?.takeIf { it.first == look }?.let { return it.second }
        val side = AvatarStore.STORED_PX
        val bitmap = Bitmap.createBitmap(side, side, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        canvas.drawColor(Color.parseColor(look.color))
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize = side * .58f
            textAlign = Paint.Align.CENTER
            typeface = Typeface.DEFAULT
        }
        val width = paint.measureText(look.emoji)
        if (width > side * .9f) paint.textSize *= side * .9f / width
        val metrics = paint.fontMetrics
        canvas.drawText(look.emoji, side / 2f, (side - metrics.ascent - metrics.descent) / 2f, paint)
        cached = look to bitmap
        return bitmap
    }
}
