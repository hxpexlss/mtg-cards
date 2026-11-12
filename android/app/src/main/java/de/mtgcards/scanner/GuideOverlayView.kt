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

    /** Querformat-Rahmen für Karten, die quer gedruckt sind (Schlachten u.ä.). */
    var landscape: Boolean = false
        set(value) {
            field = value
            computeRect(width, height)
            invalidate()
        }

    /** Code-Modus: flacher Streifen nur für den unteren Kartenrand (Set-Code + Sammlernummer). */
    var codeMode: Boolean = false
        set(value) {
            field = value
            computeRect(width, height)
            invalidate()
        }

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
        computeRect(w, h)
    }

    private fun computeRect(w: Int, h: Int) {
        if (w == 0 || h == 0) return
        if (codeMode) {
            val sw = w * 0.86f
            val sh = sw * 0.24f
            val left = (w - sw) / 2f
            val top = h * 0.40f - sh / 2f
            cardRect = RectF(left, top, left + sw, top + sh)
            return
        }
        val ratio = if (landscape) 88f / 63f else 63f / 88f   // Breite / Höhe
        val cardW = min(w * (if (landscape) 0.94f else 0.84f), h * 0.68f * ratio)
        val cardH = cardW / ratio
        val left = (w - cardW) / 2f
        val top = (h - cardH) / 2f - h * 0.04f
        cardRect = RectF(left, top, left + cardW, top + cardH)
    }

    private val hint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textAlign = Paint.Align.CENTER
        setShadowLayer(4f, 0f, 1f, Color.BLACK)
    }

    override fun onDraw(canvas: Canvas) {
        val r = cardRect ?: return
        if (codeMode) {
            path.reset()
            path.fillType = Path.FillType.EVEN_ODD
            path.addRect(0f, 0f, width.toFloat(), height.toFloat(), Path.Direction.CW)
            path.addRoundRect(r, 18f, 18f, Path.Direction.CW)
            canvas.drawPath(path, dim)
            frame.color = if (active) Color.rgb(63, 185, 80) else Color.rgb(139, 108, 255)
            canvas.drawRoundRect(r, 18f, 18f, frame)
            hint.textSize = r.height() * 0.16f
            canvas.drawText("Unteren Kartenrand hier: z.B. „0077“ und „FDN • DE“", r.centerX(),
                r.bottom + hint.textSize * 1.6f, hint)
            return
        }
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
