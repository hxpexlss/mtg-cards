package de.mtgcards.scanner

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.net.http.SslCertificate
import android.net.http.SslError
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection

/**
 * Proxie Maker: Oberfläche des Servers (/proxies/) in der App – Drucklisten, Decks, Editor, Druck.
 * Gleiche Verbindung (Adresse, Token, Zertifikat) wie MTG Cards.
 */
class ProxieActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var loadedFor = ""

    private val chooser = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val data = res.data
        val uris: Array<Uri>? = when {
            res.resultCode != RESULT_OK -> null
            data?.clipData != null -> Array(data.clipData!!.itemCount) { data.clipData!!.getItemAt(it).uri }
            data?.data != null -> arrayOf(data.data!!)
            else -> null
        }
        fileCallback?.onReceiveValue(uris)
        fileCallback = null
    }

    private val base get() = Prefs.serverUrl(this).trimEnd('/')

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val dp = resources.displayMetrics.density
        web = WebView(this).apply {
            setBackgroundColor(Color.parseColor("#12111A"))
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = false
            settings.userAgentString = settings.userAgentString + " MTGCardsApp"
        }
        val root = FrameLayout(this)
        root.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        root.addView(ImageButton(this).apply {
            setImageResource(R.drawable.ic_home)
            setBackgroundColor(Color.argb(170, 22, 20, 31))
            contentDescription = "Startmenü"
            setOnClickListener {
                StartActivity.open(this@ProxieActivity)
                finish()
            }
        }, FrameLayout.LayoutParams((44 * dp).toInt(), (44 * dp).toInt(), Gravity.BOTTOM or Gravity.START).apply {
            setMargins((10 * dp).toInt(), 0, 0, (10 * dp).toInt())
        })
        setContentView(root)

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, req: WebResourceRequest): Boolean {
                val url = req.url.toString()
                if (url.startsWith("$base/proxies")) return false
                if (url.startsWith(base)) {                 // Link zu MTG Cards -> Startmenü
                    StartActivity.open(this@ProxieActivity)
                    finish()
                    return true
                }
                try { startActivity(Intent(Intent.ACTION_VIEW, req.url)) } catch (_: ActivityNotFoundException) {}
                return true
            }

            @SuppressLint("WebViewClientOnReceivedSslError")
            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
                val fp = fingerprintOf(error.certificate)
                val pin = Prefs.fingerprint(this@ProxieActivity)
                if (fp != null && pin.isNotBlank() && Tls.normalize(fp) == Tls.normalize(pin) && error.url.startsWith(base)) {
                    handler.proceed()
                } else {
                    handler.cancel()
                    AlertDialog.Builder(this@ProxieActivity).setTitle("Zertifikat nicht bestätigt")
                        .setMessage("Das Zertifikat des Servers passt nicht zum gespeicherten Fingerabdruck.\n\n${fp ?: ""}\n\n" +
                            "Bitte in MTG Cards unter „Verbindung“ neu verbinden.")
                        .setPositiveButton("OK", null).show()
                }
            }

            override fun onReceivedError(view: WebView, req: WebResourceRequest, err: WebResourceError) {
                if (req.isForMainFrame) {
                    loadedFor = ""
                    view.loadDataWithBaseURL(null, "<html><body style='background:#12111a;color:#ece9f7;font-family:sans-serif;" +
                        "padding:30px;text-align:center'><h2>Server nicht erreichbar</h2><p>$base</p><p style='color:#9a95b3'>" +
                        "${err.description}</p><p><a style='color:#e2a03f' href='$base/proxies/'>Erneut versuchen</a></p></body></html>",
                        "text/html", "utf-8", null)
                }
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(view: WebView, cb: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = cb
                return try {
                    chooser.launch(params.createIntent().apply {
                        if (params.mode == FileChooserParams.MODE_OPEN_MULTIPLE) putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                    })
                    true
                } catch (e: ActivityNotFoundException) {
                    fileCallback = null
                    false
                }
            }
        }
        web.setDownloadListener { url, _, disposition, mime, _ -> download(url, mime, disposition) }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                web.evaluateJavascript(
                    "(function(){var d=[].slice.call(document.querySelectorAll('dialog[open]')).pop();" +
                        "if(d){d.close();return 1}var s=document.querySelector('.sidebar.open');" +
                        "if(s){s.classList.remove('open');return 1}return 0})()") { r ->
                    if (r != "1") {
                        if (web.canGoBack()) web.goBack() else {
                            StartActivity.open(this@ProxieActivity)
                            finish()
                        }
                    }
                }
            }
        })
    }

    override fun onResume() {
        super.onResume()
        val key = base + "|" + Prefs.token(this)
        if (key != loadedFor) {
            loadedFor = key
            web.loadUrl("$base/proxies/#token=${Uri.encode(Prefs.token(this))}")
        }
    }

    private fun fingerprintOf(cert: SslCertificate): String? {
        val der = SslCertificate.saveState(cert)?.getByteArray("x509-certificate") ?: return null
        return try {
            Tls.fingerprint(CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(der)) as X509Certificate)
        } catch (e: Exception) {
            null
        }
    }

    /** PDF / ZIP / Sicherung laden (mit Zertifikats-Pinning) und zum Öffnen, Drucken oder Teilen anbieten. */
    private fun download(url: String, mime: String?, disposition: String?) {
        Toast.makeText(this, "Wird erstellt – Kartenbilder werden geladen …", Toast.LENGTH_LONG).show()
        lifecycleScope.launch {
            try {
                val (bytes, name) = withContext(Dispatchers.IO) {
                    val conn = URL(url).openConnection() as HttpURLConnection
                    if (conn is HttpsURLConnection) Tls.configure(conn, Prefs.fingerprint(this@ProxieActivity))
                    conn.connectTimeout = 10000
                    conn.readTimeout = 240000
                    conn.setRequestProperty("Authorization", "Bearer ${Prefs.token(this@ProxieActivity)}")
                    try {
                        val code = conn.responseCode
                        if (code !in 200..299) {
                            val msg = conn.errorStream?.bufferedReader()?.use { it.readText() } ?: ""
                            throw RuntimeException(try { JSONObject(msg).optString("error") } catch (e: Exception) { "Fehler $code" })
                        }
                        val n = conn.getHeaderField("Content-Disposition")?.let {
                            Regex("filename=\"?([^\";]+)").find(it)?.groupValues?.get(1)
                        }
                        conn.inputStream.use { it.readBytes() } to n
                    } finally {
                        conn.disconnect()
                    }
                }
                val fileName = name ?: Regex("filename=\"?([^\";]+)").find(disposition ?: "")?.groupValues?.get(1)
                    ?: "proxie-maker-download"
                val type = when {
                    fileName.endsWith(".pdf") -> "application/pdf"
                    fileName.endsWith(".zip") -> "application/zip"
                    fileName.endsWith(".json") -> "application/json"
                    fileName.endsWith(".txt") -> "text/plain"
                    else -> mime ?: "application/octet-stream"
                }
                val file = withContext(Dispatchers.IO) {
                    File(File(cacheDir, "pdf").apply { mkdirs() }, fileName).apply { writeBytes(bytes) }
                }
                val uri = FileProvider.getUriForFile(this@ProxieActivity, "$packageName.files", file)
                val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, type).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                val send = Intent(Intent.ACTION_SEND).setType(type).putExtra(Intent.EXTRA_STREAM, uri)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                if (type == "application/pdf") {
                    Toast.makeText(this@ProxieActivity, "Beim Drucken 100 % / tatsächliche Größe wählen", Toast.LENGTH_LONG).show()
                    try {
                        startActivity(Intent.createChooser(view, "PDF öffnen"))
                        return@launch
                    } catch (_: ActivityNotFoundException) {
                    }
                }
                startActivity(Intent.createChooser(send, "Speichern oder teilen"))
            } catch (e: Exception) {
                Toast.makeText(this@ProxieActivity, "Fehler: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }
}
