package de.mtgcards.scanner

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ImageDecoder
import android.graphics.Paint
import android.graphics.RectF
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.text.InputType
import android.util.Base64
import android.util.LruCache
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import kotlin.math.max

/** Eigene Proxies: Bilder (Fun-Karten, Alters …) hochladen, speichern und als PDF drucken. */
class CustomProxiesActivity : AppCompatActivity() {
    private lateinit var info: TextView
    private val adapter = CustomAdapter()
    private var items: List<JSONObject> = emptyList()
    private var replaceId = 0L

    private val pickImages = registerForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
        if (uris.isNotEmpty()) askNameAndUpload(uris)
    }
    private val pickReplacement = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null && replaceId > 0) replaceImage(replaceId, uri)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val dp = resources.displayMetrics.density
        fun px(v: Int) = (v * dp).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(12), px(4), px(12), 0)
        }
        root.addView(LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            addView(ImageButton(this@CustomProxiesActivity).apply {
                setImageResource(R.drawable.ic_back)
                setBackgroundResource(android.R.color.transparent)
                contentDescription = "Zurück"
                setOnClickListener { finish() }
            }, LinearLayout.LayoutParams(px(48), px(48)))
            addView(TextView(this@CustomProxiesActivity).apply {
                text = "Eigene Proxies"
                textSize = 22f
                setTypeface(typeface, android.graphics.Typeface.BOLD)
            })
        })
        root.addView(LinearLayout(this).apply {
            addView(Button(this@CustomProxiesActivity).apply {
                text = "＋ Bilder hinzufügen"
                setOnClickListener { pickImages.launch("image/*") }
            }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(Button(this@CustomProxiesActivity).apply {
                text = "🖨 Drucken (PDF)"
                setOnClickListener {
                    if (items.isEmpty()) Toast.makeText(context, "Noch keine eigenen Proxies", Toast.LENGTH_SHORT).show()
                    else ProxyPdf.ask(this@CustomProxiesActivity, lifecycleScope, "/api/custom-proxies/proxies.pdf",
                        "proxies-eigene.pdf")
                }
            }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        })
        info = TextView(this).apply {
            textSize = 13f
            setPadding(0, px(6), 0, px(6))
        }
        root.addView(info)
        root.addView(RecyclerView(this).apply {
            layoutManager = GridLayoutManager(this@CustomProxiesActivity, 3)
            adapter = this@CustomProxiesActivity.adapter
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
        load()
    }

    private fun load() {
        lifecycleScope.launch {
            try {
                val arr = Api.fromPrefs(this@CustomProxiesActivity).customProxies().getJSONArray("items")
                items = (0 until arr.length()).map { arr.getJSONObject(it) }
                adapter.notifyDataSetChanged()
                val copies = items.sumOf { it.optInt("quantity") }
                info.text = if (items.isEmpty()) "Noch keine eigenen Proxies. Bilder von Fun-Karten, Alters oder selbst " +
                    "gestalteten Karten hinzufügen – sie werden ins Kartenformat gebracht, gespeichert und lassen sich " +
                    "als PDF (9 pro Seite) drucken."
                else "${items.size} Karten · $copies Exemplare · antippen zum Bearbeiten"
            } catch (e: ApiException) {
                info.text = e.message
            }
        }
    }

    private fun displayName(uri: Uri): String = try {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0)?.substringBeforeLast('.') else null
        } ?: "Eigene Karte"
    } catch (e: Exception) {
        "Eigene Karte"
    }

    private fun askNameAndUpload(uris: List<Uri>) {
        val name = EditText(this).apply {
            hint = if (uris.size == 1) "Name" else "Name (leer = Dateinamen)"
            if (uris.size == 1) setText(displayName(uris[0]))
            isSingleLine = true
        }
        val qty = EditText(this).apply {
            hint = "Anzahl"
            inputType = InputType.TYPE_CLASS_NUMBER
            setText("1")
        }
        var fit = 0
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 16, 48, 0)
            addView(name)
            addView(qty)
        }
        AlertDialog.Builder(this)
            .setTitle(if (uris.size == 1) "Eigener Proxy" else "${uris.size} Bilder hochladen")
            .setView(box)
            .setSingleChoiceItems(arrayOf("Auf Kartenformat zuschneiden", "Ganzes Bild (weißer Rand)"), 0) { _, w -> fit = w }
            .setPositiveButton("Hochladen") { _, _ ->
                upload(uris, name.text.toString().trim(), qty.text.toString().toIntOrNull() ?: 1, fit == 1)
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    private fun upload(uris: List<Uri>, givenName: String, quantity: Int, contain: Boolean) {
        Toast.makeText(this, "Lade hoch …", Toast.LENGTH_SHORT).show()
        lifecycleScope.launch {
            var ok = 0
            for ((i, uri) in uris.withIndex()) {
                try {
                    val b64 = withContext(Dispatchers.Default) { toCardJpeg(uri, contain) }
                    val name = when {
                        givenName.isBlank() -> displayName(uri)
                        uris.size > 1 -> "$givenName ${i + 1}"
                        else -> givenName
                    }
                    Api.fromPrefs(this@CustomProxiesActivity).customAdd(name, b64, quantity.coerceAtLeast(1))
                    ok++
                } catch (e: ApiException) {
                    Toast.makeText(this@CustomProxiesActivity, e.message, Toast.LENGTH_LONG).show()
                } catch (e: Exception) {
                    Toast.makeText(this@CustomProxiesActivity, "Bild nicht lesbar: ${e.message}", Toast.LENGTH_LONG).show()
                }
            }
            if (ok > 0) Toast.makeText(this@CustomProxiesActivity, "$ok gespeichert", Toast.LENGTH_SHORT).show()
            load()
        }
    }

    /** Bild laden (Drehung aus den Kameradaten berücksichtigt), ins Kartenformat bringen, als JPEG (Base64). */
    private fun toCardJpeg(uri: Uri, contain: Boolean): String {
        val src: Bitmap = if (Build.VERSION.SDK_INT >= 28) {
            ImageDecoder.decodeBitmap(ImageDecoder.createSource(contentResolver, uri)) { dec, info, _ ->
                val s = max(info.size.width, info.size.height)
                if (s > 2400) dec.setTargetSampleSize((s / 2400f).toInt().coerceAtLeast(1) + 1)
                dec.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            }
        } else {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
            var sample = 1
            while (max(bounds.outWidth, bounds.outHeight) / sample > 2400) sample *= 2
            contentResolver.openInputStream(uri)?.use {
                BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
            } ?: throw IllegalArgumentException("kein Bild")
        }
        val out = Bitmap.createBitmap(CARD_W, CARD_H, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(out)
        canvas.drawColor(Color.WHITE)
        val scale = if (contain) minOf(CARD_W / src.width.toFloat(), CARD_H / src.height.toFloat())
        else max(CARD_W / src.width.toFloat(), CARD_H / src.height.toFloat())
        val w = src.width * scale
        val h = src.height * scale
        canvas.drawBitmap(src, null, RectF((CARD_W - w) / 2, (CARD_H - h) / 2, (CARD_W + w) / 2, (CARD_H + h) / 2),
            Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG))
        src.recycle()
        val bytes = ByteArrayOutputStream().use { os ->
            out.compress(Bitmap.CompressFormat.JPEG, 90, os)
            os.toByteArray()
        }
        out.recycle()
        return Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    private fun edit(p: JSONObject) {
        val id = p.optLong("id")
        val name = EditText(this).apply { setText(p.optString("name")); isSingleLine = true; hint = "Name" }
        val qty = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER
            setText(p.optInt("quantity").toString())
            hint = "Anzahl"
        }
        val notes = EditText(this).apply { setText(p.optString("notes")); hint = "Notiz (optional)" }
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 16, 48, 0)
            addView(name)
            addView(qty)
            addView(notes)
        }
        AlertDialog.Builder(this)
            .setTitle(p.optString("name"))
            .setView(box)
            .setPositiveButton("Speichern") { _, _ ->
                change(id, JSONObject().put("name", name.text.toString().trim())
                    .put("quantity", qty.text.toString().toIntOrNull() ?: 1).put("notes", notes.text.toString()))
            }
            .setNeutralButton("Mehr …") { _, _ ->
                AlertDialog.Builder(this)
                    .setItems(arrayOf("Bild ersetzen", "Löschen")) { _, which ->
                        if (which == 0) {
                            replaceId = id
                            pickReplacement.launch("image/*")
                        } else confirmDelete(p)
                    }
                    .show()
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    private fun confirmDelete(p: JSONObject) {
        AlertDialog.Builder(this)
            .setTitle("„${p.optString("name")}“ löschen?")
            .setPositiveButton("Löschen") { _, _ ->
                lifecycleScope.launch {
                    try {
                        Api.fromPrefs(this@CustomProxiesActivity).customDelete(p.optLong("id"))
                        load()
                    } catch (e: ApiException) {
                        Toast.makeText(this@CustomProxiesActivity, e.message, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    private fun replaceImage(id: Long, uri: Uri) {
        lifecycleScope.launch {
            try {
                val b64 = withContext(Dispatchers.Default) { toCardJpeg(uri, false) }
                change(id, JSONObject().put("image", b64))
            } catch (e: Exception) {
                Toast.makeText(this@CustomProxiesActivity, "Bild nicht lesbar: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun change(id: Long, changes: JSONObject) {
        lifecycleScope.launch {
            try {
                Api.fromPrefs(this@CustomProxiesActivity).customUpdate(id, changes)
                load()
            } catch (e: ApiException) {
                Toast.makeText(this@CustomProxiesActivity, e.message, Toast.LENGTH_LONG).show()
            }
        }
    }

    // ------------------------------------------------------------------ Liste (3 Spalten)
    private inner class CustomAdapter : RecyclerView.Adapter<CustomAdapter.VH>() {
        inner class VH(val box: LinearLayout, val image: ImageView, val label: TextView) : RecyclerView.ViewHolder(box)

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val dp = parent.resources.displayMetrics.density
            val image = ImageView(parent.context).apply {
                scaleType = ImageView.ScaleType.CENTER_CROP
                adjustViewBounds = true
            }
            val label = TextView(parent.context).apply {
                textSize = 12f
                maxLines = 2
                gravity = Gravity.CENTER_HORIZONTAL
            }
            val box = LinearLayout(parent.context).apply {
                orientation = LinearLayout.VERTICAL
                setPadding((4 * dp).toInt(), (4 * dp).toInt(), (4 * dp).toInt(), (8 * dp).toInt())
                addView(image, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, (150 * dp).toInt()))
                addView(label)
                layoutParams = RecyclerView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            }
            return VH(box, image, label)
        }

        override fun getItemCount() = items.size

        override fun onBindViewHolder(h: VH, position: Int) {
            val p = items[position]
            h.label.text = "${p.optInt("quantity")}× ${p.optString("name")}"
            h.box.setOnClickListener { edit(p) }
            val key = "${p.optLong("id")}:${p.optString("image_version")}"
            h.image.tag = key
            thumbs.get(key)?.let { h.image.setImageBitmap(it); return }
            h.image.setImageDrawable(null)
            lifecycleScope.launch {
                try {
                    val bytes = Api.fromPrefs(this@CustomProxiesActivity).customImage(p.optLong("id"))
                    val bmp = withContext(Dispatchers.Default) {
                        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = 2 })
                    } ?: return@launch
                    thumbs.put(key, bmp)
                    if (h.image.tag == key) h.image.setImageBitmap(bmp)
                } catch (_: ApiException) {
                }
            }
        }
    }

    companion object {
        private const val CARD_W = 745
        private const val CARD_H = 1040
        private val thumbs = object : LruCache<String, Bitmap>(16 * 1024 * 1024) {
            override fun sizeOf(key: String, value: Bitmap) = value.byteCount
        }
    }
}
