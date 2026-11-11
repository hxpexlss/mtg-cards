package de.mtgcards.scanner

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import android.widget.ImageView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/** Sehr einfacher Bild-Lader mit Speicher-Cache (Kartenbilder von Scryfall). */
object ImageLoader {
    private val cache = object : LruCache<String, Bitmap>(32 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }

    fun load(scope: CoroutineScope, url: String?, view: ImageView, sampleSize: Int = 1) {
        view.tag = url
        if (url.isNullOrBlank()) {
            view.setImageDrawable(null)
            return
        }
        val key = "$url#$sampleSize"
        cache.get(key)?.let {
            view.setImageBitmap(it)
            return
        }
        view.setImageDrawable(null)
        scope.launch {
            val bmp = withContext(Dispatchers.IO) {
                try {
                    val conn = URL(url).openConnection() as HttpURLConnection
                    conn.connectTimeout = 8000
                    conn.readTimeout = 15000
                    conn.setRequestProperty("User-Agent", "MTGCardsScanner/1.0")
                    conn.inputStream.use {
                        BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sampleSize })
                    }
                } catch (e: Exception) {
                    null
                }
            }
            if (bmp != null) {
                cache.put(key, bmp)
                if (view.tag == url) view.setImageBitmap(bmp)
            }
        }
    }
}
