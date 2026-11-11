package de.mtgcards.scanner

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.RectF
import android.os.Bundle
import android.os.SystemClock
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.google.android.material.materialswitch.MaterialSwitch
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.max

class ScanFragment : Fragment(R.layout.fragment_scan) {

    private lateinit var previewView: PreviewView
    private lateinit var overlay: GuideOverlayView
    private lateinit var status: TextView
    private lateinit var autoSwitch: MaterialSwitch
    private lateinit var panel: View
    private lateinit var resImage: ImageView
    private lateinit var resName: TextView
    private lateinit var resInfo: TextView
    private lateinit var resOwned: TextView
    private lateinit var resTags: TextView
    private lateinit var qtyView: TextView
    private lateinit var foilCheck: CheckBox
    private lateinit var addButton: Button

    private var camera: Camera? = null
    private lateinit var executor: ExecutorService
    private val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)

    @Volatile private var paused = false
    private var lastAnalysis = 0L
    private var lastCandidate: String? = null
    private var blockedName: String? = null
    private var currentCard: JSONObject? = null
    private var quantity = 1
    private var torchOn = false

    private val permission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startCamera() else status.text = "Kamera-Berechtigung wird zum Scannen benötigt"
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        executor = Executors.newSingleThreadExecutor()
        previewView = view.findViewById(R.id.previewView)
        overlay = view.findViewById(R.id.overlay)
        status = view.findViewById(R.id.status)
        autoSwitch = view.findViewById(R.id.autoAdd)
        panel = view.findViewById(R.id.resultPanel)
        resImage = view.findViewById(R.id.resImage)
        resName = view.findViewById(R.id.resName)
        resInfo = view.findViewById(R.id.resInfo)
        resOwned = view.findViewById(R.id.resOwned)
        resTags = view.findViewById(R.id.resTags)
        qtyView = view.findViewById(R.id.qty)
        foilCheck = view.findViewById(R.id.foil)
        addButton = view.findViewById(R.id.btnAdd)

        autoSwitch.isChecked = Prefs.autoAdd(requireContext())
        autoSwitch.setOnCheckedChangeListener { _, checked -> Prefs.setAutoAdd(requireContext(), checked) }

        view.findViewById<ImageButton>(R.id.btnTorch).setOnClickListener {
            torchOn = !torchOn
            camera?.cameraControl?.enableTorch(torchOn)
        }
        view.findViewById<Button>(R.id.btnManual).setOnClickListener { manualEntry() }
        view.findViewById<Button>(R.id.btnMinus).setOnClickListener { setQty(quantity - 1) }
        view.findViewById<Button>(R.id.btnPlus).setOnClickListener { setQty(quantity + 1) }
        view.findViewById<Button>(R.id.btnDiscard).setOnClickListener { dismissResult() }
        addButton.setOnClickListener { currentCard?.let { addCard(it, quantity, foilCheck.isChecked) } }

        if (Prefs.serverUrl(requireContext()).isBlank()) {
            status.text = "Bitte zuerst unter Einstellungen den PC/Server verbinden"
        }
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) startCamera() else permission.launch(Manifest.permission.CAMERA)
    }

    override fun onDestroy() {
        super.onDestroy()
        if (::executor.isInitialized) executor.shutdown()
        recognizer.close()
    }

    // ------------------------------------------------------------------ Kamera
    private fun startCamera() {
        val ctx = context ?: return
        val future = ProcessCameraProvider.getInstance(ctx)
        future.addListener({
            if (!isAdded || view == null) return@addListener
            val provider = future.get()
            val selector = ResolutionSelector.Builder()
                .setAspectRatioStrategy(AspectRatioStrategy.RATIO_16_9_FALLBACK_AUTO_STRATEGY)
                .build()
            val preview = Preview.Builder().setResolutionSelector(selector).build()
            preview.setSurfaceProvider(previewView.surfaceProvider)
            val analysis = ImageAnalysis.Builder()
                .setResolutionSelector(selector)
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
            analysis.setAnalyzer(executor) { proxy -> analyze(proxy) }
            try {
                provider.unbindAll()
                camera = provider.bindToLifecycle(viewLifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
            } catch (e: Exception) {
                status.text = "Kamera konnte nicht gestartet werden: ${e.message}"
            }
        }, ContextCompat.getMainExecutor(ctx))
    }

    @androidx.annotation.OptIn(ExperimentalGetImage::class)
    private fun analyze(proxy: ImageProxy) {
        val now = SystemClock.elapsedRealtime()
        val media = proxy.image
        if (paused || media == null || now - lastAnalysis < 450) {
            proxy.close()
            return
        }
        lastAnalysis = now
        val rot = proxy.imageInfo.rotationDegrees
        val iw = if (rot % 180 == 0) proxy.width else proxy.height
        val ih = if (rot % 180 == 0) proxy.height else proxy.width
        recognizer.process(InputImage.fromMediaImage(media, rot))
            .addOnSuccessListener { text -> onText(text, iw, ih) }
            .addOnCompleteListener { proxy.close() }
    }

    /** Rechnet den Rahmen aus View- in Bildkoordinaten um (PreviewView: FILL_CENTER). */
    private fun toImageRegion(r: RectF, vw: Float, vh: Float, iw: Float, ih: Float): Region {
        val scale = max(vw / iw, vh / ih)
        val dx = (iw * scale - vw) / 2f
        val dy = (ih * scale - vh) / 2f
        return Region((r.left + dx) / scale, (r.top + dy) / scale, (r.right + dx) / scale, (r.bottom + dy) / scale)
    }

    private fun onText(text: Text, iw: Int, ih: Int) {
        if (paused || !isAdded || view == null) return
        val rect = overlay.cardRect ?: return
        val region = toImageRegion(rect, overlay.width.toFloat(), overlay.height.toFloat(), iw.toFloat(), ih.toFloat())
        val lines = text.textBlocks.flatMap { it.lines }.mapNotNull { l ->
            l.boundingBox?.let { b -> OcrLine(l.text, b.left, b.top, b.right, b.bottom) }
        }
        val res = CardTextParser.parse(lines, region)
        val name = res.name
        if (name == null || name.length < 3) {
            lastCandidate = null
            blockedName = null
            overlay.active = false
            status.text = "Karte in den Rahmen halten – Name im violetten Feld"
            return
        }
        val key = CardTextParser.normalize(name)
        if (key == blockedName) {
            status.text = "✓ Nächste Karte in den Rahmen halten"
            return
        }
        overlay.active = true
        if (key != lastCandidate) {
            lastCandidate = key   // erst bei zweimal gleichem Ergebnis nachschlagen
            status.text = "Erkenne: $name …"
            return
        }
        lookup(name, res.setCode, res.collectorNumber)
    }

    // ------------------------------------------------------------------ Nachschlagen / Hinzufügen
    private fun lookup(name: String, setCode: String?, cn: String?) {
        paused = true
        status.text = "Suche „$name“ …"
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val card = Api.fromPrefs(requireContext()).lookup(name, setCode, cn)
                if (autoSwitch.isChecked) {
                    addCard(card, 1, foilCheck.isChecked)
                } else {
                    showResult(card)
                }
            } catch (e: ApiException) {
                status.text = e.message
                blockedName = CardTextParser.normalize(name)
                overlay.active = false
                delay(if (e.code == 404) 900L else 2500L)
                paused = false
            }
        }
    }

    private fun showResult(card: JSONObject) {
        currentCard = card
        setQty(1)
        resName.text = card.optString("name")
        val printed = card.optString("printed_name")
        val setLine = "${card.optString("set_name")} (${card.optString("set_code")}) #${card.optString("collector_number")}"
        resInfo.text = buildString {
            if (printed.isNotBlank() && printed != card.optString("name")) append(printed).append('\n')
            append(card.optString("type_line")).append('\n').append(setLine)
            val ci = card.optString("color_identity").ifBlank { "farblos" }
            append("\nFarbidentität: ").append(ci)
        }
        val owned = card.optJSONObject("owned")
        resOwned.text = "Im Bestand: ${owned?.optInt("this_print") ?: 0} (dieser Druck) · ${owned?.optInt("all_prints") ?: 0} gesamt"
        val tags = card.optJSONArray("auto_tags")
        val tagList = (0 until (tags?.length() ?: 0)).map { tags!!.getString(it) }
        resTags.text = tagList.joinToString("  ") { "#$it" }
        resTags.visibility = if (tagList.isEmpty()) View.GONE else View.VISIBLE
        ImageLoader.load(viewLifecycleOwner.lifecycleScope, card.optString("image_url"), resImage, 2)
        panel.visibility = View.VISIBLE
        status.text = "Gefunden – hinzufügen oder verwerfen"
    }

    private fun setQty(q: Int) {
        quantity = q.coerceIn(1, 99)
        qtyView.text = quantity.toString()
    }

    private fun addCard(card: JSONObject, qty: Int, foil: Boolean) {
        addButton.isEnabled = false
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val res = Api.fromPrefs(requireContext()).addCard(card.getString("scryfall_id"), qty, foil)
                Toast.makeText(requireContext(),
                    "✓ ${res.optString("name")} – jetzt ${res.optInt("quantity")}×", Toast.LENGTH_SHORT).show()
                status.text = "✓ ${res.optString("name")} hinzugefügt"
                dismissResult()
            } catch (e: ApiException) {
                Toast.makeText(requireContext(), e.message, Toast.LENGTH_LONG).show()
                if (panel.visibility != View.VISIBLE) showResult(card)
            } finally {
                addButton.isEnabled = true
            }
        }
    }

    private fun dismissResult() {
        panel.visibility = View.GONE
        currentCard = null
        blockedName = lastCandidate
        overlay.active = false
        paused = false
    }

    private fun manualEntry() {
        val input = EditText(requireContext()).apply {
            hint = "Kartenname"
            isSingleLine = true
            imeOptions = EditorInfo.IME_ACTION_SEARCH
        }
        val dialog = AlertDialog.Builder(requireContext())
            .setTitle("Karte per Name suchen")
            .setView(input)
            .setPositiveButton("Suchen") { _, _ ->
                val n = input.text.toString().trim()
                if (n.isNotEmpty()) {
                    lastCandidate = CardTextParser.normalize(n)
                    lookup(n, null, null)
                }
            }
            .setNegativeButton("Abbrechen", null)
            .create()
        dialog.setOnShowListener { input.requestFocus() }
        dialog.show()
    }
}
