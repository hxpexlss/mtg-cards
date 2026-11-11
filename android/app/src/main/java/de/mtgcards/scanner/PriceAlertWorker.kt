package de.mtgcards.scanner

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/** Prüft regelmäßig die Wunschliste und benachrichtigt, wenn eine Karte den Zielpreis erreicht. */
class PriceAlertWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    companion object {
        private const val CHANNEL = "price_alerts"
        private const val WORK = "price-alerts"

        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<PriceAlertWorker>(6, TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.KEEP, req)
        }
    }

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        if (Prefs.serverUrl(ctx).isBlank()) return Result.success()
        val res = try { Api.fromPrefs(ctx).wishlist() } catch (e: ApiException) { return Result.retry() }
        val arr = res.getJSONArray("items")
        val sp = ctx.getSharedPreferences("mtgcards", Context.MODE_PRIVATE)
        val notified = sp.getStringSet("notified_wishes", emptySet())!!.toMutableSet()
        val current = mutableSetOf<String>()
        val fresh = mutableListOf<String>()
        for (i in 0 until arr.length()) {
            val w = arr.getJSONObject(i)
            if (!w.optBoolean("target_reached")) continue
            // Schlüssel: Wunsch + Zeitpunkt, an dem der Zielpreis erreicht wurde -> erneut melden nach Wiederanstieg
            val key = "${w.optLong("id")}@${w.optString("target_reached_at")}"
            current += key
            if (key !in notified) {
                fresh += "${w.optString("name")}: ${euro(w.optDouble("price_eur"))} (Ziel ${euro(w.optDouble("max_price_eur"))})"
            }
        }
        sp.edit().putStringSet("notified_wishes", current).apply()
        if (fresh.isNotEmpty()) notify(ctx, fresh)
        return Result.success()
    }

    private fun notify(ctx: Context, lines: List<String>) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) return
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Preis-Alarm Wunschliste",
                NotificationManager.IMPORTANCE_DEFAULT))
        }
        val open = PendingIntent.getActivity(ctx, 0,
            Intent(ctx, MainActivity::class.java).putExtra("tab", "wishlist"),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val title = if (lines.size == 1) "Zielpreis erreicht" else "${lines.size} Karten unter Zielpreis"
        val n = NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_wish)
            .setContentTitle(title)
            .setContentText(lines.first())
            .setStyle(NotificationCompat.BigTextStyle().bigText(lines.joinToString("\n")))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(ctx).notify(4711, n)
        } catch (_: SecurityException) {
        }
    }
}
