package de.mtgcards.scanner

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import kotlin.math.min

/** Zeichnet den Kartenrahmen, in den die Karte gehalten wird, und markiert den Namensbereich. */
class GuideOverlayView @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    /** Kartenrahmen in View-Koordinaten. */
    @Volatile
    var cardRect: RectF? = null
        private set

    var active: Boolean = false
        set(value) {
            field = value
            invalidate()
        }

    private val dim = Paint().apply { color = Color.argb(140, 0, 0, 0) }
    private val frame = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 5f
        color = Color.WHITE
    }
    private val nameArea = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.argb(60, 139, 108, 255)
    }
    private val nameStroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 3f
        color = Color.rgb(139, 108, 255)
    }
    private val path = Path()

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        val cardW = min(w * 0.84f, h * 0.68f * 63f / 88f)
        val cardH = cardW * 88f / 63f
        val left = (w - cardW) / 2f
        val top = (h - cardH) / 2f - h * 0.04f
        cardRect = RectF(left, top, left + cardW, top + cardH)
    }

    override fun onDraw(canvas: Canvas) {
        val r = cardRect ?: return
        val radius = r.width() * 0.045f
        path.reset()
        path.fillType = Path.FillType.EVEN_ODD
        path.addRect(0f, 0f, width.toFloat(), height.toFloat(), Path.Direction.CW)
        path.addRoundRect(r, radius, radius, Path.Direction.CW)
        canvas.drawPath(path, dim)
        frame.color = if (active) Color.rgb(63, 185, 80) else Color.WHITE
        canvas.drawRoundRect(r, radius, radius, frame)
        val name = RectF(r.left + r.width() * 0.04f, r.top + r.height() * 0.03f,
            r.right - r.width() * 0.04f, r.top + r.height() * 0.11f)
        canvas.drawRoundRect(name, 12f, 12f, nameArea)
        canvas.drawRoundRect(name, 12f, 12f, nameStroke)
    }
}
