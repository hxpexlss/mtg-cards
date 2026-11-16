package de.mtgcards.scanner

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.CheckBox
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/** Startmenü: MTG Cards (Sammlung, Scanner, Decks …) oder Proxie Maker (Proxies gestalten und drucken). */
class StartActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_MENU = "menu"
        private fun sp(ctx: Context) = ctx.getSharedPreferences("mtgcards", Context.MODE_PRIVATE)
        fun choice(ctx: Context) = sp(ctx).getString("start_choice", "") ?: ""
        fun setChoice(ctx: Context, v: String) = sp(ctx).edit().putString("start_choice", v).apply()

        /** Aus beiden Teilen zurück ins Startmenü. */
        fun open(ctx: Context) {
            ctx.startActivity(Intent(ctx, StartActivity::class.java).putExtra(EXTRA_MENU, true)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val configured = Prefs.serverUrl(this).isNotBlank()
        // Gemerkte Auswahl direkt öffnen (außer das Menü wurde ausdrücklich aufgerufen)
        if (configured && savedInstanceState == null && !intent.getBooleanExtra(EXTRA_MENU, false)) {
            when (choice(this)) {
                "mtg" -> { openMtg(); finish(); return }
                "pm" -> { openProxies(); finish(); return }
            }
        }
        val dp = resources.displayMetrics.density
        fun px(v: Int) = (v * dp).toInt()
        val remember = CheckBox(this).apply {
            text = "Auswahl merken und beim nächsten Start direkt öffnen"
            isChecked = choice(this@StartActivity).isNotBlank()
            setOnCheckedChangeListener { _, on -> if (!on) setChoice(this@StartActivity, "") }
        }

        fun tile(title: String, sub: String, icon: Int, color: String, onClick: () -> Unit) = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(px(18), px(22), px(18), px(22))
            background = GradientDrawable().apply {
                cornerRadius = 22 * dp
                setColor(Color.parseColor("#22202F"))
                setStroke(px(2), Color.parseColor(color))
            }
            addView(ImageView(context).apply { setImageResource(icon) }, LinearLayout.LayoutParams(px(72), px(72)))
            addView(TextView(context).apply {
                text = title
                textSize = 22f
                setTypeface(typeface, Typeface.BOLD)
                setTextColor(Color.WHITE)
                gravity = Gravity.CENTER
                setPadding(0, px(8), 0, px(2))
            })
            addView(TextView(context).apply {
                text = sub
                textSize = 14f
                setTextColor(Color.parseColor("#B8B3CF"))
                gravity = Gravity.CENTER
            })
            setOnClickListener { onClick() }
        }

        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(px(20), px(36), px(20), px(20))
            addView(TextView(context).apply {
                text = "Was möchtest du öffnen?"
                textSize = 24f
                setTypeface(typeface, Typeface.BOLD)
                gravity = Gravity.CENTER
                setPadding(0, 0, 0, px(22))
            })
            val lp = { LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                .apply { bottomMargin = px(16) } }
            addView(tile("MTG Cards", "Scannen, Sammlung, Decks, Wunschliste", R.drawable.ic_launcher, "#8B6CFF") {
                if (remember.isChecked) setChoice(this@StartActivity, "mtg")
                openMtg()
            }, lp())
            addView(tile("Proxie Maker", "Proxies personalisieren und drucken", R.drawable.ic_proxies, "#E2A03F") {
                if (remember.isChecked) setChoice(this@StartActivity, "pm")
                openProxies()
            }, lp())
            addView(tile("🔍 Karte nachschlagen", "Ansehen, dann auf die Wunschliste oder in Proxie Maker",
                R.drawable.ic_search, "#3FB950") {
                if (Prefs.serverUrl(this@StartActivity).isBlank()) openMtg()
                else startActivity(Intent(this@StartActivity, LookupActivity::class.java))
            }, lp())
            addView(remember)
            addView(TextView(context).apply {
                text = if (configured) "Verbunden mit ${Prefs.serverUrl(this@StartActivity)}  ·  ändern unter MTG Cards → Verbindung"
                else "Noch keine Verbindung – zuerst MTG Cards öffnen und unter „Verbindung“ den Server eintragen."
                textSize = 12f
                setTextColor(Color.parseColor("#9A95B3"))
                gravity = Gravity.CENTER
                setPadding(0, px(18), 0, 0)
            })
        }
        setContentView(ScrollView(this).apply { addView(box) })
    }

    private fun openMtg() = startActivity(Intent(this, MainActivity::class.java))

    private fun openProxies() {
        if (Prefs.serverUrl(this).isBlank()) {
            startActivity(Intent(this, MainActivity::class.java))   // zuerst Verbindung einrichten
            return
        }
        startActivity(Intent(this, ProxieActivity::class.java))
    }
}
