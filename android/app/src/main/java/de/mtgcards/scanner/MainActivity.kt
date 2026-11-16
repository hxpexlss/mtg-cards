package de.mtgcards.scanner

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.google.android.material.bottomnavigation.BottomNavigationView

class MainActivity : AppCompatActivity() {

    private lateinit var nav: BottomNavigationView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        nav = findViewById(R.id.bottomNav)
        findViewById<android.view.View>(R.id.btnHomeFloat).setOnClickListener {
            StartActivity.open(this)
            finish()
        }
        if (Prefs.serverUrl(this).isNotBlank()) PriceAlertWorker.schedule(this)
        if (savedInstanceState == null) {
            val start = when {
                Prefs.serverUrl(this).isBlank() -> R.id.nav_settings
                intent.getStringExtra("tab") == "wishlist" -> R.id.nav_wishlist
                else -> R.id.nav_scan
            }
            nav.selectedItemId = start
            show(start)
        }
        nav.setOnItemSelectedListener { item ->
            show(item.itemId)
            true
        }
    }

    fun selectTab(id: Int) {
        nav.selectedItemId = id
    }

    private fun show(id: Int) {
        val fragment: Fragment = when (id) {
            R.id.nav_search -> SearchFragment()
            R.id.nav_decks -> DecksFragment()
            R.id.nav_wishlist -> WishlistFragment()
            R.id.nav_settings -> SettingsFragment()
            else -> ScanFragment()
        }
        supportFragmentManager.beginTransaction().replace(R.id.container, fragment).commit()
        // Im Scan-Bildschirm sitzt der Knopf oben links (unten liegen dort die Bedienelemente)
        findViewById<android.view.View>(R.id.btnHomeFloat).visibility =
            if (fragment is ScanFragment) android.view.View.GONE else android.view.View.VISIBLE
    }
}
