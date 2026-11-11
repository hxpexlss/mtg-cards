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
        if (savedInstanceState == null) {
            val start = if (Prefs.serverUrl(this).isBlank()) R.id.nav_settings else R.id.nav_scan
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
            R.id.nav_settings -> SettingsFragment()
            else -> ScanFragment()
        }
        supportFragmentManager.beginTransaction().replace(R.id.container, fragment).commit()
    }
}
