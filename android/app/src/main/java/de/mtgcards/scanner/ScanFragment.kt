package de.mtgcards.scanner

import android.Manifest
import androidx.core.widget.doAfterTextChanged
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.core.UseCaseGroup
import android.util.Size
import android.graphics.Rect
import android.graphics.Bitmap
import android.graphics.BitmapRegionDecoder
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.RectF
import android.os.Bundle
import android.os.SystemClock
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.Spinner
import android.widget.ArrayAdapter
import android.widget.AdapterView
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
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.materialswitch.MaterialSwitch
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
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
    private lateinit var pendingView: TextView
    private lateinit var sessionView: TextView
    private lateinit var recentList: RecyclerView
    private lateinit var recentAdapter: RecentAdapter
    private lateinit var batchSwitch: MaterialSwitch
    private lateinit var proxySwitch: MaterialSwitch
    private lateinit var modeInfo: TextView
    private lateinit var menu: View
    private lateinit var scrim: View
    private var deckChoices: List<Pair<Long, String>> = listOf(0L to "Kein Deck")
    @Volatile private var viewportBound = false
    private val setVotes = mutableListOf<String>()
    private val cnVotes = mutableListOf<String>()
    private val langVotes = mutableListOf<String>()
    private var waitFrames = 0
    private var lastCode: String? = null
    private val codeSetVotes = mutableListOf<String>()
    private val codeCnVotes = mutableListOf<String>()
    private val codeLangVotes = mutableListOf<String>()
    private var emptyFrames = 0
    private var blockedFailed = false
    // alte Karten: Kartenanzahl der Edition ("123/249"), Künstler, Jahr
    private val totalVotes = mutableListOf<String>()
    private val artistVotes = mutableListOf<String>()
    private val yearVotes = mutableListOf<String>()
    /** Farbsignatur des Artworks der gerade erkannten Karte (für den Artwork-Vergleich). */
    private var artSig: FloatArray? = null
    /** Fotos in voller Auflösung für den Code-Modus (null, wenn das Gerät es nicht zusammen mit der Analyse kann). */
    private var imageCapture: ImageCapture? = null
    private var codeJob: Job? = null
    private var lastFocus = 0L
    private lateinit var batchButton: Button

    private var camera: Camera? = null
    private lateinit var executor: ExecutorService
    private val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    private val feedback = Feedback()
    private val voter = CandidateVoter()

    @Volatile private var paused = false
    private var lastAnalysis = 0L
    private var lastCandidate: String? = null
    private var blockedName: String? = null
    private var currentCard: JSONObject? = null
    private var currentScan: ScanResult? = null
    private var quantity = 1
    private var torchOn = false
    private var syncing = false

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
        pendingView = view.findViewById(R.id.pending)
        sessionView = view.findViewById(R.id.sessionCount)
        recentList = view.findViewById(R.id.recent)
        batchSwitch = view.findViewById(R.id.batchMode)
        proxySwitch = view.findViewById(R.id.proxyMode)
        proxySwitch.isChecked = Prefs.proxyMode(requireContext())
        proxySwitch.setOnCheckedChangeListener { _, on ->
            Prefs.setProxyMode(requireContext(), on)
            status.text = if (on) "🅿 Proxy-Modus: nur der Name zählt, gespeichert wird der Standard-Druck" else "Proxy-Modus aus"
            resetVotes()
            clearCodeVotes()
            applyGuideMode()
            refreshModeInfo()
        }
        batchButton = view.findViewById(R.id.btnBatch)
        batchSwitch.isChecked = BatchStore.isEnabled(requireContext())
        batchSwitch.setOnCheckedChangeListener { _, on ->
            BatchStore.setEnabled(requireContext(), on)
            status.text = if (on) "Stapel-Modus: Karten werden gesammelt und am Ende gespeichert" else "Einzel-Modus"
            refreshBatchButton()
            refreshModeInfo()
        }
        batchButton.setOnClickListener { startActivity(Intent(requireContext(), BatchActivity::class.java)) }

        recentAdapter = RecentAdapter(viewLifecycleOwner.lifecycleScope) { scan -> recentActions(scan) }
        recentList.layoutManager = LinearLayoutManager(requireContext(), LinearLayoutManager.HORIZONTAL, false)
        recentList.adapter = recentAdapter

        autoSwitch.isChecked = Prefs.autoAdd(requireContext())
        autoSwitch.setOnCheckedChangeListener { _, checked ->
            Prefs.setAutoAdd(requireContext(), checked)
            refreshModeInfo()
        }
        setupMenu(view)   // nach den Schaltern, damit die Modus-Zeile stimmt

        view.findViewById<ImageButton>(R.id.btnTorch).setOnClickListener {
            torchOn = !torchOn
            camera?.cameraControl?.enableTorch(torchOn)
        }
        view.findViewById<Button>(R.id.btnManual).setOnClickListener { manualEntry() }
        overlay.landscape = Prefs.landscape(requireContext())
        view.findViewById<Button>(R.id.btnMinus).setOnClickListener { setQty(quantity - 1) }
        view.findViewById<Button>(R.id.btnPlus).setOnClickListener { setQty(quantity + 1) }
        view.findViewById<Button>(R.id.btnDiscard).setOnClickListener { dismissResult() }
        view.findViewById<Button>(R.id.btnPrint).setOnClickListener {
            val c = currentCard ?: return@setOnClickListener
            PrintPicker.show(requireContext(), viewLifecycleOwner.lifecycleScope, c.optString("name"),
                c.optString("lang")) { picked -> showResult(picked) }
        }
        addButton.setOnClickListener { currentCard?.let { addCard(it, quantity, foilCheck.isChecked) } }
        pendingView.setOnClickListener { syncPending(manual = true) }

        setupGestures()
        refreshSessionViews()

        if (Prefs.serverUrl(requireContext()).isBlank()) {
            status.text = "Bitte zuerst unter Verbindung den PC/Server eintragen"
        }
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) startCamera() else permission.launch(Manifest.permission.CAMERA)

        syncPending(manual = false)
        // Offline gemerkte Scans regelmäßig nachtragen, solange die Scan-Ansicht offen ist
        viewLifecycleOwner.lifecycleScope.launch {
            while (true) {
                delay(30_000L)
                syncPending(manual = false)
            }
        }
    }

    private val proxy get() = proxySwitch.isChecked

    private val targetDeck get() = Prefs.scanDeckId(requireContext())

    // ------------------------------------------------------------------ Seitenmenü
    private fun setupMenu(view: View) {
        val ctx = requireContext()
        menu = view.findViewById(R.id.scanMenu)
        scrim = view.findViewById(R.id.menuScrim)
        modeInfo = view.findViewById(R.id.modeInfo)
        view.findViewById<ImageButton>(R.id.btnMenu).setOnClickListener { openMenu() }
        view.findViewById<ImageButton>(R.id.btnMenuClose).setOnClickListener { closeMenu() }
        scrim.setOnClickListener { closeMenu() }

        // Sprache
        val langSpinner = view.findViewById<Spinner>(R.id.langSpinner)
        langSpinner.adapter = ArrayAdapter(ctx, android.R.layout.simple_spinner_dropdown_item, Languages.all.map { it.second })
        langSpinner.setSelection(Languages.all.indexOfFirst { it.first == Prefs.scanLang(ctx) }.coerceAtLeast(0), false)
        langSpinner.onItemSelectedListener = simpleSelect { pos ->
            Prefs.setScanLang(ctx, Languages.all[pos].first)
            refreshModeInfo()
        }

        // Foil, Querformat, Ton
        view.findViewById<MaterialSwitch>(R.id.foilDefault).apply {
            isChecked = Prefs.defaultFoil(ctx)
            foilCheck.isChecked = isChecked
            setOnCheckedChangeListener { _, on ->
                Prefs.setDefaultFoil(ctx, on)
                foilCheck.isChecked = on
                refreshModeInfo()
            }
        }
        overlay.landscape = Prefs.landscape(ctx)
        val guide = this.overlay   // in apply{} wäre "overlay" die View-Eigenschaft des Schalters
        applyGuideMode()
        view.findViewById<MaterialSwitch>(R.id.codeMode).apply {
            isChecked = Prefs.codeMode(ctx)
            setOnCheckedChangeListener { _, on ->
                Prefs.setCodeMode(ctx, on)
                applyGuideMode()
                voter.reset()
                resetVotes()
                clearCodeVotes()
                lastCode = null
                status.text = when {
                    on && proxy -> "Code-Modus pausiert, solange der Proxy-Modus an ist"
                    on -> "Code-Modus: unteren Kartenrand in den Streifen halten"
                    else -> "Namens-Modus"
                }
                refreshModeInfo()
            }
        }
        view.findViewById<EditText>(R.id.fixedSet).apply {
            setText(Prefs.fixedSet(ctx))
            doAfterTextChanged { t ->
                Prefs.setFixedSet(ctx, t?.toString() ?: "")
                refreshModeInfo()
            }
        }
        view.findViewById<MaterialSwitch>(R.id.landscapeMode).apply {
            isChecked = guide.landscape
            setOnCheckedChangeListener { _, on ->
                guide.landscape = on
                Prefs.setLandscape(ctx, on)
                voter.reset()
                refreshModeInfo()
            }
        }
        view.findViewById<MaterialSwitch>(R.id.soundMode).apply {
            isChecked = Prefs.sound(ctx)
            setOnCheckedChangeListener { _, on -> Prefs.setSound(ctx, on) }
        }

        // Ziel-Deck
        setDeckChoices(view, listOf(0L to "Kein Deck") +
            (if (Prefs.scanDeckId(ctx) > 0) listOf(Prefs.scanDeckId(ctx) to Prefs.scanDeckName(ctx)) else emptyList()))
        loadDecks(view)
        refreshModeInfo()
    }

    private fun setDeckChoices(view: View, choices: List<Pair<Long, String>>) {
        val ctx = requireContext()
        deckChoices = choices
        val spinner = view.findViewById<Spinner>(R.id.deckSpinner)
        spinner.onItemSelectedListener = null
        spinner.adapter = ArrayAdapter(ctx, android.R.layout.simple_spinner_dropdown_item, choices.map { it.second })
        spinner.setSelection(choices.indexOfFirst { it.first == Prefs.scanDeckId(ctx) }.coerceAtLeast(0), false)
        spinner.onItemSelectedListener = simpleSelect { pos ->
            val (id, name) = deckChoices[pos]
            Prefs.setScanDeck(ctx, id, if (id > 0) name else "")
            refreshModeInfo()
        }
    }

    private fun loadDecks(view: View) {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val arr = Api.fromPrefs(requireContext()).decks().getJSONArray("decks")
                val list = (0 until arr.length()).map { arr.getJSONObject(it) }
                    .sortedWith(compareBy({ it.optString("status") == "owned" }, { it.optString("name").lowercase() }))
                    .map { it.optLong("id") to (it.optString("name") +
                        if (it.optString("status") == "owned") " (Besitz)" else " (Bau)") }
                val current = Prefs.scanDeckId(requireContext())
                if (current > 0 && list.none { it.first == current }) Prefs.setScanDeck(requireContext(), 0L, "")
                setDeckChoices(view, listOf(0L to "Kein Deck") + list)
                refreshModeInfo()
            } catch (_: ApiException) {
                // offline: zuletzt gewähltes Deck bleibt im Menü
            }
        }
    }

    private fun simpleSelect(onSelect: (Int) -> Unit) = object : AdapterView.OnItemSelectedListener {
        override fun onItemSelected(parent: AdapterView<*>?, v: View?, position: Int, id: Long) = onSelect(position)
        override fun onNothingSelected(parent: AdapterView<*>?) {}
    }

    private fun openMenu() {
        view?.let { loadDecks(it) }
        scrim.visibility = View.VISIBLE
        menu.visibility = View.VISIBLE
        menu.translationX = menu.width.toFloat().takeIf { it > 0 } ?: 900f
        menu.animate().translationX(0f).setDuration(180).start()
    }

    private fun closeMenu() {
        menu.animate().translationX(menu.width.toFloat()).setDuration(160).withEndAction {
            menu.visibility = View.GONE
            scrim.visibility = View.GONE
        }.start()
    }

    /** Kurze Zeile unter dem Status mit den aktiven Einstellungen. */
    private fun refreshModeInfo() {
        val ctx = context ?: return
        if (!::modeInfo.isInitialized) return
        val parts = buildList {
            if (proxySwitch.isChecked) add("🅿 Proxy")
            if (batchSwitch.isChecked) add("Stapel")
            if (autoSwitch.isChecked && !batchSwitch.isChecked) add("Auto")
            if (Prefs.defaultFoil(ctx)) add("Foil")
            if (Prefs.scanDeckId(ctx) > 0) add("→ ${Prefs.scanDeckName(ctx).substringBeforeLast(" (")}")
            Prefs.scanLang(ctx).takeIf { it != "auto" }?.let { add(it.uppercase()) }
            if (Prefs.landscape(ctx)) add("Querformat")
            if (Prefs.codeMode(ctx)) add(if (proxySwitch.isChecked) "Code-Modus (pausiert)" else "Code-Modus")
            else (Prefs.fixedSet(ctx).ifBlank { null }?.let { "Edition $it (fest)" }
                ?: Prefs.lastSet(ctx).ifBlank { null }?.let { "Edition $it" })?.let { add(it) }
        }
        modeInfo.text = parts.joinToString(" · ")
        modeInfo.visibility = if (parts.isEmpty()) View.GONE else View.VISIBLE
    }

    /** Code-Modus nur ohne Proxy-Modus (bei Proxies ist der Druck egal). */
    private fun applyGuideMode() {
        val ctx = context ?: return
        overlay.codeMode = Prefs.codeMode(ctx) && !proxySwitch.isChecked
        applyCodeZoom()
    }

    /** Im Code-Modus 2x zoomen: die Karte muss nicht so nah ans Handy (sonst stellt die Kamera nicht scharf). */
    private fun applyCodeZoom() {
        val cam = camera ?: return
        val max = cam.cameraInfo.zoomState.value?.maxZoomRatio ?: 1f
        cam.cameraControl.setZoomRatio(if (overlay.codeMode) minOf(2f, max) else 1f)
    }

    override fun onResume() {
        super.onResume()
        if (::batchButton.isInitialized) refreshBatchButton()
    }

    private fun refreshBatchButton() {
        val ctx = context ?: return
        val n = BatchStore.count(ctx)
        batchButton.visibility = if (n > 0) View.VISIBLE else View.GONE
        batchButton.text = "✓ Stapel abschließen – $n Karten · ${euro(BatchStore.value(ctx))}"
    }

    private fun addToBatch(item: BatchItem, card: JSONObject? = null) {
        val qty = BatchStore.add(requireContext(), item)
        feedback.success(overlay, sound)
        val price = item.unitPrice?.let { " · ${euro(it)}" } ?: ""
        val where = item.setCode?.let { " · $it #${item.cn}" } ?: ""
        val sure = card?.let { PrintPicker.matchText(it).take(1).let { m -> if (m.isNotBlank()) " $m" else "" } } ?: ""
        status.text = "＋ ${item.name.ifBlank { where.trim(' ', '·') }}$where$price$sure" + if (qty > 1) " (jetzt ${qty}×)" else ""
        refreshBatchButton()
    }

    override fun onDestroyView() {
        codeJob?.cancel()
        codeJob = null
        super.onDestroyView()
    }

    override fun onDestroy() {
        super.onDestroy()
        if (::executor.isInitialized) executor.shutdown()
        recognizer.close()
        feedback.release()
    }

    private val sound get() = Prefs.sound(requireContext())

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
            // Texterkennung in Full-HD: die kleine Zeile unten (Set-Code, Nummer) ist sonst kaum lesbar
            val analysisSelector = ResolutionSelector.Builder()
                .setAspectRatioStrategy(AspectRatioStrategy.RATIO_16_9_FALLBACK_AUTO_STRATEGY)
                .setResolutionStrategy(ResolutionStrategy(Size(1920, 1080),
                    ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
                .build()
            val preview = Preview.Builder().setResolutionSelector(selector).build()
            preview.setSurfaceProvider(previewView.surfaceProvider)
            val analysis = ImageAnalysis.Builder()
                .setResolutionSelector(analysisSelector)
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
            analysis.setAnalyzer(executor) { frame -> analyze(frame) }
            // Code-Modus: echte Fotos in voller Auflösung – die Schrift am Kartenrand ist nur ~1,5 mm hoch
            val capture = ImageCapture.Builder()
                .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                .setResolutionSelector(ResolutionSelector.Builder()
                    .setAspectRatioStrategy(AspectRatioStrategy.RATIO_16_9_FALLBACK_AUTO_STRATEGY)
                    .setResolutionStrategy(ResolutionStrategy.HIGHEST_AVAILABLE_STRATEGY)
                    .build())
                .build()
            fun bind(withCapture: Boolean): Camera {
                provider.unbindAll()
                val viewPort = previewView.viewPort
                val cases = listOfNotNull(preview, analysis, if (withCapture) capture else null)
                return if (viewPort != null) {
                    // gleicher sichtbarer Ausschnitt für alle -> exakte Rahmen-Umrechnung
                    val group = UseCaseGroup.Builder().setViewPort(viewPort).apply { cases.forEach { addUseCase(it) } }.build()
                    viewportBound = true
                    provider.bindToLifecycle(viewLifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, group)
                } else {
                    viewportBound = false
                    provider.bindToLifecycle(viewLifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, *cases.toTypedArray())
                }
            }
            try {
                camera = try {
                    bind(true).also { imageCapture = capture }
                } catch (e: Exception) {
                    imageCapture = null          // Gerät schafft nicht alle drei gleichzeitig -> Code-Modus über die Analyse
                    bind(false)
                }
                applyCodeZoom()
                startCodeLoop()
            } catch (e: Exception) {
                status.text = "Kamera konnte nicht gestartet werden: ${e.message}"
            }
        }, ContextCompat.getMainExecutor(ctx))
    }

    /** Tippen = scharfstellen, zwei Finger = zoomen. */
    @SuppressLint("ClickableViewAccessibility")
    private fun setupGestures() {
        val scaleDetector = ScaleGestureDetector(requireContext(),
            object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
                override fun onScale(detector: ScaleGestureDetector): Boolean {
                    val cam = camera ?: return false
                    val current = cam.cameraInfo.zoomState.value?.zoomRatio ?: 1f
                    cam.cameraControl.setZoomRatio(current * detector.scaleFactor)
                    return true
                }
            })
        overlay.setOnTouchListener { v, event ->
            scaleDetector.onTouchEvent(event)
            if (event.action == MotionEvent.ACTION_UP && !scaleDetector.isInProgress && event.pointerCount == 1) {
                val point = previewView.meteringPointFactory.createPoint(event.x, event.y)
                camera?.cameraControl?.startFocusAndMetering(FocusMeteringAction.Builder(point).build())
                v.performClick()
            }
            true
        }
    }

    @androidx.annotation.OptIn(ExperimentalGetImage::class)
    private fun analyze(frame: ImageProxy) {
        val now = SystemClock.elapsedRealtime()
        val media = frame.image
        // Im Code-Modus liest die Foto-Schleife (volle Auflösung) – die Vorschaubilder sind dafür zu klein
        if (paused || media == null || now - lastAnalysis < 280 || (overlay.codeMode && imageCapture != null)) {
            frame.close()
            return
        }
        lastAnalysis = now
        val rot = frame.imageInfo.rotationDegrees
        val iw = if (rot % 180 == 0) frame.width else frame.height
        val ih = if (rot % 180 == 0) frame.height else frame.width
        val crop = if (viewportBound) uprightCrop(frame.cropRect, frame.width, frame.height, rot) else null
        recognizer.process(InputImage.fromMediaImage(media, rot))
            .addOnCompleteListener { task ->
                // Bild erst nach der Auswertung freigeben (Artwork-Ausschnitt wird daraus genommen)
                try {
                    if (task.isSuccessful) onText(task.result, iw, ih, crop, frame)
                } finally {
                    frame.close()
                }
            }
    }

    // ------------------------------------------------------------------ Code-Modus: Fotos in voller Auflösung
    private fun startCodeLoop() {
        codeJob?.cancel()
        if (imageCapture == null) return
        codeJob = viewLifecycleOwner.lifecycleScope.launch {
            while (true) {
                if (overlay.codeMode && !paused && isResumed) {
                    try {
                        captureCode()
                    } catch (e: Exception) {
                        if (e is kotlinx.coroutines.CancellationException) throw e
                        delay(500L)
                    }
                    delay(120L)
                } else {
                    delay(250L)
                }
            }
        }
    }

    private suspend fun captureCode() {
        val cap = imageCapture ?: return
        val rect = overlay.cardRect ?: return
        val vw = overlay.width.toFloat()
        val vh = overlay.height.toFloat()
        focusStrip(rect)
        val strip: Bitmap = suspendCancellableCoroutine<Bitmap?> { cont ->
            cap.takePicture(executor, object : ImageCapture.OnImageCapturedCallback() {
                override fun onCaptureSuccess(image: ImageProxy) {
                    val bmp = try { cropStrip(image, rect, vw, vh) } catch (e: Exception) { null } finally { image.close() }
                    if (cont.isActive) cont.resume(bmp)
                }

                override fun onError(exception: ImageCaptureException) {
                    if (cont.isActive) cont.resume(null)
                }
            })
        } ?: return
        val lines = recognize(strip)
        if (!overlay.codeMode || paused || view == null) return
        // Der Ausschnitt ist der Streifen plus Rand – Region = Streifen
        val padX = strip.width * STRIP_PAD_X / (1 + 2 * STRIP_PAD_X)
        val padY = strip.height * STRIP_PAD_Y / (1 + 2 * STRIP_PAD_Y)
        onCodeText(lines, Region(padX, padY, strip.width - padX, strip.height - padY))
    }

    private suspend fun recognize(bmp: Bitmap): List<OcrLine> = suspendCancellableCoroutine { cont ->
        recognizer.process(InputImage.fromBitmap(bmp, 0))
            .addOnSuccessListener { text ->
                val lines = text.textBlocks.flatMap { it.lines }.mapNotNull { l ->
                    l.boundingBox?.let { b -> OcrLine(l.text, b.left, b.top, b.right, b.bottom) }
                }
                if (cont.isActive) cont.resume(lines)
            }
            .addOnFailureListener { if (cont.isActive) cont.resume(emptyList()) }
    }

    /** Alle 2,5 s auf den Streifen scharfstellen (Nahbereich). */
    private fun focusStrip(rect: RectF) {
        val now = SystemClock.elapsedRealtime()
        if (now - lastFocus < 2500L) return
        lastFocus = now
        val point = previewView.meteringPointFactory.createPoint(rect.centerX(), rect.centerY())
        camera?.cameraControl?.startFocusAndMetering(
            FocusMeteringAction.Builder(point, FocusMeteringAction.FLAG_AF or FocusMeteringAction.FLAG_AE)
                .setAutoCancelDuration(3, TimeUnit.SECONDS).build())
    }

    /** Streifen (plus Rand) aus dem Foto schneiden – nur dieser Teil wird dekodiert, dann aufrecht gedreht. */
    @Suppress("DEPRECATION")
    private fun cropStrip(image: ImageProxy, rect: RectF, vw: Float, vh: Float): Bitmap? {
        val rot = image.imageInfo.rotationDegrees
        val w = image.width
        val h = image.height
        val uw = (if (rot % 180 == 0) w else h).toFloat()
        val uh = (if (rot % 180 == 0) h else w).toFloat()
        val region = if (viewportBound) toCropRegion(rect, vw, vh, uprightCrop(image.cropRect, w, h, rot))
        else toImageRegion(rect, vw, vh, uw, uh)
        val padX = (region.right - region.left) * STRIP_PAD_X
        val padY = (region.bottom - region.top) * STRIP_PAD_Y
        val up = RectF(region.left - padX, region.top - padY, region.right + padX, region.bottom + padY)
        if (!up.intersect(0f, 0f, uw, uh)) return null
        val s = sensorRect(up, w, h, rot)
        if (s.width() < 8 || s.height() < 8) return null
        val part: Bitmap = if (image.format == ImageFormat.JPEG) {
            val buf = image.planes[0].buffer
            buf.rewind()
            val bytes = ByteArray(buf.remaining()).also { buf.get(it) }
            BitmapRegionDecoder.newInstance(bytes, 0, bytes.size, false)?.decodeRegion(s, null) ?: return null
        } else {
            val full = image.toBitmap()
            Bitmap.createBitmap(full, s.left, s.top, s.width(), s.height())
        }
        val upright = if (rot != 0) Bitmap.createBitmap(part, 0, 0, part.width, part.height,
            Matrix().apply { postRotate(rot.toFloat()) }, true) else part
        val f = minOf(1f, 2200f / upright.width)
        return if (f < 1f) Bitmap.createScaledBitmap(upright, (upright.width * f).toInt(), (upright.height * f).toInt(), true)
        else upright
    }

    /** Umkehrung von uprightCrop: Rechteck in aufrechten Koordinaten -> Sensor-/Bildkoordinaten. */
    private fun sensorRect(u: RectF, w: Int, h: Int, rot: Int): Rect {
        val r = when (rot) {
            90 -> RectF(u.top, h - u.right, u.bottom, h - u.left)
            180 -> RectF(w - u.right, h - u.bottom, w - u.left, h - u.top)
            270 -> RectF(w - u.bottom, u.left, w - u.top, u.right)
            else -> RectF(u)
        }
        return Rect(r.left.toInt().coerceIn(0, w - 1), r.top.toInt().coerceIn(0, h - 1),
            r.right.toInt().coerceIn(1, w), r.bottom.toInt().coerceIn(1, h))
    }

    /** Artwork-Bereich der Karte aus dem aktuellen Kamerabild (für den Artwork-Vergleich). */
    private fun captureArt(frame: ImageProxy, card: Region): FloatArray? = try {
        val full = frame.toBitmap()
        val rot = frame.imageInfo.rotationDegrees
        val upright = if (rot != 0) Bitmap.createBitmap(full, 0, 0, full.width, full.height,
            Matrix().apply { postRotate(rot.toFloat()) }, false) else full
        val w = card.right - card.left
        val h = card.bottom - card.top
        val l = (card.left + w * ArtMatcher.CARD_LEFT).toInt().coerceIn(0, upright.width - 2)
        val t = (card.top + h * ArtMatcher.CARD_TOP).toInt().coerceIn(0, upright.height - 2)
        val r = (card.left + w * ArtMatcher.CARD_RIGHT).toInt().coerceIn(l + 1, upright.width)
        val b = (card.top + h * ArtMatcher.CARD_BOTTOM).toInt().coerceIn(t + 1, upright.height)
        val art = Bitmap.createBitmap(upright, l, t, r - l, b - t)
        ArtMatcher.signature(art).also {
            art.recycle()
            if (upright !== full) upright.recycle()
            full.recycle()
        }
    } catch (e: Exception) {
        null
    }

    /** Rechnet den Rahmen aus View- in Bildkoordinaten um (PreviewView: FILL_CENTER). */
    private fun toImageRegion(r: RectF, vw: Float, vh: Float, iw: Float, ih: Float): Region {
        val scale = max(vw / iw, vh / ih)
        val dx = (iw * scale - vw) / 2f
        val dy = (ih * scale - vh) / 2f
        return Region((r.left + dx) / scale, (r.top + dy) / scale, (r.right + dx) / scale, (r.bottom + dy) / scale)
    }

    /** Sichtbarer Bildausschnitt (cropRect) in aufrechte Bildkoordinaten drehen (wie ML Kit sie liefert). */
    private fun uprightCrop(c: Rect, w: Int, h: Int, rot: Int): RectF = when (rot) {
        90 -> RectF((h - c.bottom).toFloat(), c.left.toFloat(), (h - c.top).toFloat(), c.right.toFloat())
        180 -> RectF((w - c.right).toFloat(), (h - c.bottom).toFloat(), (w - c.left).toFloat(), (h - c.top).toFloat())
        270 -> RectF(c.top.toFloat(), (w - c.right).toFloat(), c.bottom.toFloat(), (w - c.left).toFloat())
        else -> RectF(c)
    }

    /** Rahmen (View-Koordinaten) linear auf den sichtbaren Bildausschnitt abbilden. */
    private fun toCropRegion(r: RectF, vw: Float, vh: Float, crop: RectF): Region {
        val sx = crop.width() / vw
        val sy = crop.height() / vh
        return Region(crop.left + r.left * sx, crop.top + r.top * sy, crop.left + r.right * sx, crop.top + r.bottom * sy)
    }

    private fun mostCommon(list: List<String>): String? = list.groupingBy { it }.eachCount().maxByOrNull { it.value }?.key

    private fun resetVotes() {
        setVotes.clear()
        cnVotes.clear()
        langVotes.clear()
        totalVotes.clear()
        artistVotes.clear()
        yearVotes.clear()
        waitFrames = 0
    }

    /**
     * Sprache vom Kartenrand nur, wenn sie mehrfach gleich gelesen wurde und eine lateinische Schrift ist
     * (Japanisch, Chinesisch … kann die Texterkennung gar nicht lesen – so ein Treffer ist ein Lesefehler).
     */
    private fun votedLang(votes: List<String>): String? =
        mostCommon(votes)?.takeIf { l -> l in LATIN_LANGS && votes.count { it == l } >= 2 }

    private fun isBlocked(key: String) = blockedName?.let { similarity(it, key) >= 0.8 } ?: false

    private fun onText(text: Text, iw: Int, ih: Int, crop: RectF?, frame: ImageProxy) {
        if (paused || !isAdded || view == null) return
        val rect = overlay.cardRect ?: return
        val vw = overlay.width.toFloat()
        val vh = overlay.height.toFloat()
        val region = crop?.let { toCropRegion(rect, vw, vh, it) }
            ?: toImageRegion(rect, vw, vh, iw.toFloat(), ih.toFloat())
        val lines = text.textBlocks.flatMap { it.lines }.mapNotNull { l ->
            l.boundingBox?.let { b -> OcrLine(l.text, b.left, b.top, b.right, b.bottom) }
        }
        if (overlay.codeMode) {
            onCodeText(lines, region)
            return
        }
        val res = CardTextParser.parse(lines, region)
        val name = res.name
        if (name == null || name.length < 3) {
            lastCandidate = null
            blockedName = null
            voter.reset()
            resetVotes()
            overlay.active = false
            status.text = "Karte in den Rahmen halten – Name im violetten Feld"
            return
        }
        val key = CardTextParser.normalize(name)
        if (isBlocked(key)) {
            status.text = if (blockedFailed) "Nicht gefunden – Karte etwas anders halten oder „Name eingeben“"
            else "✓ Nächste Karte in den Rahmen halten"
            return
        }
        overlay.active = true
        if (lastCandidate != null && similarity(lastCandidate!!, key) < 0.8) resetVotes()   // andere Karte
        lastCandidate = key
        // Set-Code/Nummer über mehrere Bilder sammeln – ein einzelner Lesefehler kippt das Ergebnis nicht
        res.setCode?.let { setVotes += it }
        res.collectorNumber?.let { cnVotes += it }
        res.lang?.let { langVotes += it }
        res.total?.let { totalVotes += it }
        res.artist?.let { artistVotes += it }
        res.year?.let { yearVotes += it }
        if (!voter.offer(key)) {
            status.text = "Erkenne: $name …"
            return
        }
        if (proxy) {
            // Proxy: Druck ist egal -> sofort mit dem Namen suchen (Standard-Druck)
            voter.reset()
            feedback.found(overlay)
            val scan = res.copy(name = name, setCode = null, collectorNumber = null, lang = votedLang(langVotes),
                total = null, artist = null, year = null)
            resetVotes()
            artSig = null
            lookup(scan)
            return
        }
        if ((setVotes.isEmpty() || cnVotes.isEmpty()) && waitFrames < 3) {
            waitFrames++      // kurz weiterlesen, ob die untere Zeile noch lesbar wird
            status.text = "Erkenne: $name – lese Set-Code …"
            return
        }
        voter.reset()
        feedback.found(overlay)
        val scan = res.copy(name = name, setCode = mostCommon(setVotes) ?: res.setCode,
            collectorNumber = mostCommon(cnVotes) ?: res.collectorNumber, lang = votedLang(langVotes),
            total = mostCommon(totalVotes), artist = mostCommon(artistVotes), year = mostCommon(yearVotes))
        resetVotes()
        // Artwork merken: unterscheidet bei unsicherem Druck die Editionen mit anderem Bild
        artSig = if (!overlay.landscape && scan.setCode == null) captureArt(frame, region) else null
        lookup(scan)
    }

    /**
     * Code-Modus: nur Set-Code + Sammlernummer vom unteren Rand.
     * Wie im Namens-Modus werden die Werte über mehrere Bilder gesammelt (Mehrheitsentscheid);
     * Bilder, in denen nur ein Teil lesbar ist, zählen trotzdem mit.
     */
    private fun onCodeText(lines: List<OcrLine>, strip: Region) {
        val r = CardTextParser.parseCode(lines, strip)
        if (r.setCode == null && r.collectorNumber == null) {
            emptyFrames++
            if (emptyFrames >= 3) {          // Karte weg -> neu beginnen, Sperre aufheben
                clearCodeVotes()
                blockedName = null
                blockedFailed = false
            }
            overlay.active = false
            status.text = when {
                r.raw.isNotBlank() -> "Lese … „${r.raw.take(40)}“"
                emptyFrames >= 6 -> "Nichts lesbar – Karte etwas weiter weg halten, Licht (⚡) einschalten"
                else -> "Unteren Kartenrand in den Streifen halten (z.B. „0077“ und „FDN • DE“)"
            }
            return
        }
        emptyFrames = 0
        r.setCode?.let { codeSetVotes += it }
        r.collectorNumber?.let { codeCnVotes += it }
        r.lang?.let { codeLangVotes += it }
        for (l in listOf(codeSetVotes, codeCnVotes, codeLangVotes)) while (l.size > 8) l.removeAt(0)

        val set = mostCommon(codeSetVotes)
        val cn = mostCommon(codeCnVotes)
        val key = "$set|$cn"
        if (key == blockedName) {
            status.text = if (blockedFailed) "Nicht gefunden: $set #$cn – Karte etwas anders halten oder Licht an"
            else "✓ Nächste Karte – unteren Rand in den Streifen halten"
            return
        }
        overlay.active = true
        val sure = set != null && cn != null &&
            codeSetVotes.count { it == set } >= 2 && codeCnVotes.count { it == cn } >= 2
        if (!sure) {
            status.text = "Lese ${set ?: "?"} #${cn ?: "?"} …" + if (r.raw.isNotBlank()) "  („${r.raw.take(30)}“)" else ""
            return
        }
        val lang = votedLang(codeLangVotes)
        clearCodeVotes()
        feedback.found(overlay)
        lookup(ScanResult(null, set, cn, emptyList(), lang))
    }

    private fun clearCodeVotes() {
        codeSetVotes.clear()
        codeCnVotes.clear()
        codeLangVotes.clear()
    }

    // ------------------------------------------------------------------ Nachschlagen / Hinzufügen
    /** Gewählte Sprache; bei "Automatisch" die vom Kartenrand gelesene (sonst Englisch/Standard). */
    private fun langFor(scan: ScanResult): String? {
        val pref = Prefs.scanLang(requireContext())
        return if (pref == "auto") scan.lang else pref
    }

    private fun lookup(scan: ScanResult) {
        val codeOnly = scan.name == null
        if (codeOnly && (scan.setCode == null || scan.collectorNumber == null)) return
        val name = scan.name ?: ""
        val label = scan.name ?: "${scan.setCode} #${scan.collectorNumber}"
        val blockKey = scan.name?.let { CardTextParser.normalize(it) } ?: "${scan.setCode}|${scan.collectorNumber}"
        val preferSet = if (codeOnly || proxy) null
        else Prefs.fixedSet(requireContext()).ifBlank { Prefs.lastSet(requireContext()) }
        paused = true
        currentScan = scan
        status.text = "Suche „$label“ …"
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val api = Api.fromPrefs(requireContext())
                var card = api.lookup(scan.name, scan.setCode, scan.collectorNumber,
                    scan.alternatives, langFor(scan), preferSet = preferSet,
                    total = scan.total, artist = scan.artist, year = scan.year)
                if (proxy && !codeOnly) card.put("match", "proxy")
                else if (!codeOnly) card = refineByArt(api, card, preferSet)
                rememberSet(card, codeOnly)
                blockedFailed = false
                when {
                    batchSwitch.isChecked -> {
                        addToBatch(BatchItem.fromCard(card, foilCheck.isChecked, proxy, targetDeck), card)
                        blockedName = blockKey
                        overlay.active = false
                        delay(400L)
                        paused = false
                    }
                    autoSwitch.isChecked -> addCard(card, 1, foilCheck.isChecked)
                    else -> showResult(card)
                }
            } catch (e: ApiException) {
                blockedName = blockKey
                blockedFailed = true
                overlay.active = false
                if (e.code == Api.UNREACHABLE && batchSwitch.isChecked) {
                    // offline im Stapel: Name merken, beim Speichern wird nachgeschlagen
                    addToBatch(BatchItem(null, name, scan.setCode, scan.collectorNumber, 1, foilCheck.isChecked,
                        null, null, null, langFor(scan), proxy, targetDeck))
                    status.text = "Offline – „$label“ im Stapel (wird beim Speichern geprüft)"
                    delay(900L)
                } else if (e.code == Api.UNREACHABLE) {
                    queueOffline(PendingScan(name, scan.setCode, scan.collectorNumber, foilCheck.isChecked, 1, langFor(scan), proxy, targetDeck))
                    delay(900L)
                } else {
                    feedback.error(overlay, sound)
                    status.text = if (codeOnly && (e.code == 404 || e.code == 400))
                        "Nicht gefunden: $label – Code erneut scannen" else e.message
                    delay(if (e.code == 404) 900L else 2500L)
                }
                paused = false
            }
        }
    }

    /**
     * Unsicherer Druck (nur Name / bevorzugte Edition / Hinweise): Artwork mit den Drucken vergleichen.
     * Hilft bei Karten mit mehreren Artworks (z.B. alte Karten ohne Set-Code).
     */
    private suspend fun refineByArt(api: Api, card: JSONObject, preferSet: String?): JSONObject {
        val sig = artSig ?: return card
        artSig = null
        val match = card.optString("match")
        if (match !in listOf("name", "preferred", "likely")) return card
        status.text = "Vergleiche Artwork …"
        return try {
            val arr = api.prints(card.optString("name").split(" // ").first()).getJSONArray("data")
            val prints = (0 until arr.length()).map { arr.getJSONObject(it) }
            val best = ArtMatcher.best(sig, prints) ?: return card
            val ill = best.print.optString("illustration_id")
            if (ill.isNotBlank() && ill == card.optString("illustration_id")) {
                if (match == "name") card.put("match", "art") else card       // Artwork bestätigt den Druck
            } else {
                val group = prints.filter { it.optString("illustration_id") == ill }.ifEmpty { listOf(best.print) }
                val pick = group.lastOrNull { !preferSet.isNullOrBlank() && it.optString("set_code").equals(preferSet, true) }
                    ?: group.last()
                api.lookup(null, scryfallId = pick.optString("scryfall_id"),
                    lang = card.optString("lang").takeIf { it.isNotBlank() && it != "en" && it != "null" })
                    .put("match", "art")
            }
        } catch (e: ApiException) {
            card
        }
    }

    /** Sicher erkannte Edition merken (wird bevorzugt, wenn beim nächsten Scan unten nichts lesbar ist). */
    private fun rememberSet(card: JSONObject, codeOnly: Boolean) {
        if (codeOnly || card.optString("match") in listOf("exact", "set")) {
            card.optString("set_code").takeIf { it.isNotBlank() }?.let { Prefs.setLastSet(requireContext(), it) }
            refreshModeInfo()
        }
    }

    private fun queueOffline(p: PendingScan) {
        PendingQueue.add(requireContext(), p)
        val label = p.name.ifBlank { "${p.setCode} #${p.cn}" }
        ScanSession.push(RecentScan(0L, label, null, p.quantity, pending = true))
        feedback.success(overlay, sound)
        status.text = "Offline – „$label“ in Warteschlange"
        refreshSessionViews()
    }

    private fun showResult(card: JSONObject) {
        currentCard = card
        setQty(1)
        resName.text = card.optString("name")
        val printed = card.optString("printed_name")
        val setLine = "${card.optString("set_name")} (${card.optString("set_code")}) #${card.optString("collector_number")}"
        resInfo.text = buildString {
            if (printed.isNotBlank() && printed != "null" && printed != card.optString("name")) append(printed).append('\n')
            append(card.optString("type_line")).append('\n').append(setLine)
            append("\nFarbidentität: ").append(card.optString("color_identity").ifBlank { "farblos" })
            PrintPicker.matchText(card).takeIf { it.isNotBlank() }?.let { append("\n").append(it) }
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
                val res = Api.fromPrefs(requireContext()).addCard(card.getString("scryfall_id"), qty, foil, proxyTags(proxy), targetDeck)
                ScanSession.added += qty
                ScanSession.push(RecentScan(res.optLong("id"), res.optString("name"), res.optString("image_url"), res.optInt("quantity")))
                feedback.success(overlay, sound)
                val deckName = res.optJSONObject("deck")?.optString("name")
                status.text = "✓ ${if (res.optBoolean("proxy")) "🅿 " else ""}${res.optString("name")} – jetzt ${res.optInt("quantity")}×" +
                    (deckName?.let { " → $it" } ?: "")
                val wishes = res.optJSONArray("wish_fulfilled")
                if (wishes != null && wishes.length() > 0) {
                    Toast.makeText(requireContext(), "★ Wunsch erfüllt: ${wishes.getJSONObject(0).optString("name")}",
                        Toast.LENGTH_LONG).show()
                }
                refreshSessionViews()
                dismissResult()
                syncPending(manual = false)
            } catch (e: ApiException) {
                if (e.code == Api.UNREACHABLE) {
                    queueOffline(PendingScan(card.optString("name"), card.optString("set_code"),
                        card.optString("collector_number"), foil, qty, card.optString("lang").ifBlank { null }, proxy, targetDeck))
                    dismissResult()
                } else {
                    feedback.error(overlay, sound)
                    Toast.makeText(requireContext(), e.message, Toast.LENGTH_LONG).show()
                    if (panel.visibility != View.VISIBLE) showResult(card)
                }
            } finally {
                addButton.isEnabled = true
            }
        }
    }

    private fun dismissResult() {
        panel.visibility = View.GONE
        foilCheck.isChecked = Prefs.defaultFoil(requireContext())
        currentCard = null
        blockedName = lastCandidate
        overlay.active = false
        paused = false
    }

    // ------------------------------------------------------------------ Offline-Warteschlange
    private fun syncPending(manual: Boolean) {
        val ctx = context ?: return
        if (syncing || PendingQueue.size(ctx) == 0) return
        syncing = true
        viewLifecycleOwner.lifecycleScope.launch {
            val api = Api.fromPrefs(ctx)
            val remaining = mutableListOf<PendingScan>()
            val failed = mutableListOf<String>()
            var sent = 0
            var offline = false
            for (p in PendingQueue.all(ctx)) {
                if (offline) {
                    remaining += p
                    continue
                }
                try {
                    val res = api.addByName(p.name, p.setCode, p.cn, p.quantity, p.foil, p.lang, proxyTags(p.proxy), p.deckId)
                    sent += p.quantity
                    ScanSession.added += p.quantity
                    ScanSession.recent.removeAll { it.pending && it.name == p.name }
                    ScanSession.push(RecentScan(res.optLong("id"), res.optString("name"), res.optString("image_url"), res.optInt("quantity")))
                } catch (e: ApiException) {
                    if (e.code == Api.UNREACHABLE || e.code == Api.NOT_CONFIGURED || e.code == 401 || e.code >= 500) {
                        offline = true
                        remaining += p
                    } else {
                        failed += p.name   // z.B. 404: Name falsch erkannt
                        ScanSession.recent.removeAll { it.pending && it.name == p.name }
                    }
                }
            }
            PendingQueue.save(ctx, remaining)
            syncing = false
            if (view == null) return@launch
            refreshSessionViews()
            if (sent > 0) Toast.makeText(ctx, "$sent Karten aus der Warteschlange gesendet", Toast.LENGTH_SHORT).show()
            if (failed.isNotEmpty()) {
                AlertDialog.Builder(ctx)
                    .setTitle("Nicht gefunden")
                    .setMessage("Diese Scans konnten keiner Karte zugeordnet werden:\n\n" + failed.joinToString("\n"))
                    .setPositiveButton("OK", null)
                    .show()
            }
            if (manual && offline) Toast.makeText(ctx, "Server weiterhin nicht erreichbar", Toast.LENGTH_SHORT).show()
        }
    }

    // ------------------------------------------------------------------ Verlauf
    private fun refreshSessionViews() {
        val ctx = context ?: return
        val pending = PendingQueue.size(ctx)
        pendingView.visibility = if (pending > 0) View.VISIBLE else View.GONE
        pendingView.text = "⏳ $pending in Warteschlange – tippen zum Senden"
        sessionView.visibility = if (ScanSession.added > 0) View.VISIBLE else View.GONE
        sessionView.text = "${ScanSession.added} Karten in dieser Sitzung"
        recentAdapter.submit(ScanSession.recent.toList())
        recentList.visibility = if (ScanSession.recent.isEmpty()) View.GONE else View.VISIBLE
    }

    private fun recentActions(scan: RecentScan) {
        if (scan.pending) {
            Toast.makeText(requireContext(), "Wartet auf Verbindung", Toast.LENGTH_SHORT).show()
            return
        }
        AlertDialog.Builder(requireContext())
            .setTitle("${scan.name} (${scan.quantity}×)")
            .setItems(arrayOf("Rückgängig (−1)", "Noch ein Exemplar (+1)", "Details öffnen")) { _, which ->
                when (which) {
                    0 -> changeQuantity(scan, -1)
                    1 -> changeQuantity(scan, +1)
                    else -> startActivity(Intent(requireContext(), CardDetailActivity::class.java).putExtra("id", scan.cardId))
                }
            }
            .show()
    }

    private fun changeQuantity(scan: RecentScan, delta: Int) {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val api = Api.fromPrefs(requireContext())
                val current = api.card(scan.cardId).optInt("quantity")
                val res = api.update(scan.cardId, JSONObject().put("quantity", current + delta))
                ScanSession.added = maxOf(0, ScanSession.added + delta)
                if (res.optBoolean("deleted")) {
                    ScanSession.recent.remove(scan)
                    status.text = "${scan.name} entfernt"
                } else {
                    scan.quantity = res.optInt("quantity")
                    status.text = "${scan.name}: jetzt ${scan.quantity}×"
                }
                feedback.success(overlay, false)
                refreshSessionViews()
            } catch (e: ApiException) {
                Toast.makeText(requireContext(), e.message, Toast.LENGTH_LONG).show()
            }
        }
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
                    lookup(ScanResult(n, null, null))
                }
            }
            .setNegativeButton("Abbrechen", null)
            .create()
        dialog.setOnShowListener { input.requestFocus() }
        dialog.show()
    }
}

/** Horizontale Leiste mit den zuletzt gescannten Karten. */
class RecentAdapter(
    private val scope: CoroutineScope,
    private val onClick: (RecentScan) -> Unit,
) : RecyclerView.Adapter<RecentAdapter.VH>() {
    private var items: List<RecentScan> = emptyList()

    fun submit(list: List<RecentScan>) {
        items = list
        notifyDataSetChanged()
    }

    class VH(v: View) : RecyclerView.ViewHolder(v) {
        val image: ImageView = v.findViewById(R.id.recentImage)
        val name: TextView = v.findViewById(R.id.recentName)
        val qty: TextView = v.findViewById(R.id.recentQty)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_recent, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val s = items[position]
        holder.name.text = s.name
        holder.qty.text = if (s.pending) "⏳" else "${s.quantity}×"
        holder.image.alpha = if (s.pending) 0.4f else 1f
        ImageLoader.load(scope, s.imageUrl, holder.image, 4)
        holder.itemView.setOnClickListener { onClick(s) }
    }
}

private const val STRIP_PAD_X = 0.06f
private const val STRIP_PAD_Y = 0.30f
private val LATIN_LANGS = setOf("en", "de", "fr", "it", "es", "pt")
