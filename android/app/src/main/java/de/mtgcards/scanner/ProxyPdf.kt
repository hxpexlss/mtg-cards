package de.mtgcards.scanner

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.core.content.FileProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** Proxy-PDF vom Server laden und zum Drucken/Teilen öffnen (9 Karten pro Seite, Originalgröße). */
object ProxyPdf {
    fun ask(ctx: Context, scope: CoroutineScope, path: String, fileName: String) {
        val papers = arrayOf("A4", "US Letter")
        var paper = 0
        AlertDialog.Builder(ctx)
            .setTitle("Proxies drucken (PDF)")
            .setSingleChoiceItems(papers, 0) { _, which -> paper = which }
            .setPositiveButton("PDF erstellen") { _, _ ->
                val sep = if (path.contains("?")) "&" else "?"
                load(ctx, scope, "$path${sep}paper=${if (paper == 1) "letter" else "a4"}", fileName)
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    private fun load(ctx: Context, scope: CoroutineScope, path: String, fileName: String) {
        Toast.makeText(ctx, "PDF wird erstellt – Kartenbilder werden geladen …", Toast.LENGTH_LONG).show()
        scope.launch {
            try {
                val bytes = Api.fromPrefs(ctx).download(path)
                val file = withContext(Dispatchers.IO) {
                    val dir = File(ctx.cacheDir, "pdf").apply { mkdirs() }
                    File(dir, fileName).apply { writeBytes(bytes) }
                }
                val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.files", file)
                val view = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, "application/pdf")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                val send = Intent(Intent.ACTION_SEND).apply {
                    type = "application/pdf"
                    putExtra(Intent.EXTRA_STREAM, uri)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                Toast.makeText(ctx, "Zum Drucken: 100 % / tatsächliche Größe wählen", Toast.LENGTH_LONG).show()
                try {
                    ctx.startActivity(Intent.createChooser(view, "Proxy-PDF öffnen"))
                } catch (e: ActivityNotFoundException) {
                    ctx.startActivity(Intent.createChooser(send, "PDF teilen"))
                }
            } catch (e: ApiException) {
                Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
            }
        }
    }
}
