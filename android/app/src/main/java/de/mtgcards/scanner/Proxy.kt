package de.mtgcards.scanner

/** Tag für Proxy-Karten (wird getrennt von echten Karten gezählt). */
const val PROXY_TAG = "Proxies"

fun proxyTags(proxy: Boolean): List<String> = if (proxy) listOf(PROXY_TAG) else emptyList()
