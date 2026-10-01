package ir.dnsradar.app

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import androidx.appcompat.app.AppCompatActivity
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat

/**
 * اپ رادار DNS — پوسته‌ی سبک مرورگر دور نسخه‌ی وبِ رادار.
 * صفحه‌ها از assets (پوشه‌ی web پروژه) با منبع امن https://appassets.androidplatform.net سرو می‌شوند
 * تا fetch برای DoH بدون مشکل مبدأ (origin) کار کند.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var assetLoader: WebViewAssetLoader

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        webView = findViewById(R.id.webview)

        assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = false
            displayZoomControls = false
        }

        // پل نیتیو ← صفحه: ویجت را با آخرین نتیجهٔ سنجش به‌روز می‌کند.
        webView.addJavascriptInterface(JsBridge(), "phNative")

        webView.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(
                view: WebView, request: WebResourceRequest
            ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(
                view: WebView, request: WebResourceRequest
            ): Boolean {
                val host = request.url.host ?: return false
                if (host == "appassets.androidplatform.net") return false
                // لینک‌های بیرونی در مرورگر باز شوند
                return try {
                    startActivity(Intent(Intent.ACTION_VIEW, request.url))
                    true
                } catch (e: Exception) { false }
            }
        }

        webView.loadUrl("https://appassets.androidplatform.net/assets/dns-radar.html")
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (this::webView.isInitialized && webView.canGoBack()) webView.goBack()
        else @Suppress("DEPRECATION") super.onBackPressed()
    }

    /**
     * پلی که صفحهٔ وب می‌تواند صدا بزند: window.phNative.saveWidget(json)
     * فقط چند عدد و متن کوتاه ذخیره می‌شود؛ هیچ دادهٔ شناسایی‌کننده‌ای این‌جا رد و بدل نمی‌شود.
     */
    inner class JsBridge {
        @JavascriptInterface
        fun saveWidget(json: String?): Boolean {
            return try {
                val o = org.json.JSONObject(json ?: "{}")
                val e = getSharedPreferences(PingWidget.PREFS, MODE_PRIVATE).edit()
                if (o.has("ms")) e.putInt("ms", o.optInt("ms", -1))
                if (o.has("score")) e.putInt("score", o.optInt("score", -1))
                if (o.has("status")) e.putString("status", o.optString("status").take(48))
                if (o.has("sub")) e.putString("sub", o.optString("sub").take(48))
                e.putLong("at", System.currentTimeMillis())
                e.apply()
                PingWidget.updateAll(this@MainActivity)
                true
            } catch (t: Throwable) {
                false
            }
        }

        @JavascriptInterface
        fun isNative(): Boolean = true

        @JavascriptInterface
        fun version(): String = "2.7"

        // ---------- «حالت DNS روی گوشی» ----------
        @JavascriptInterface
        fun openDnsChanger() {
            try { startActivity(Intent(this@MainActivity, DnsChangerActivity::class.java)) } catch (_: Throwable) {}
        }

        /** وضعیت زندهٔ حالت DNS برای نمایش در صفحهٔ وب (JSON کوتاه). */
        @JavascriptInterface
        fun dnsStatus(): String {
            return try {
                val s = DnsVpnService.snapshot()
                org.json.JSONObject()
                    .put("running", s.running).put("label", s.label).put("since", s.since)
                    .put("sent", s.sent).put("answered", s.answered).put("failed", s.failed)
                    .put("loss", s.lossPct).put("last", s.lastRtt ?: -1).put("avg", s.avgRtt ?: -1)
                    .put("jitter", s.jitter ?: -1).put("error", s.error ?: "")
                    .toString()
            } catch (t: Throwable) { "{}" }
        }

        // ---------- 🎯 اسکنر IP و DNS ----------
        /** سنجش واقعی از خط خودِ گوشی: UDP/53 + TCP/port برای هر هدف. */
        @JavascriptInterface
        fun scanIps(ipsJson: String?, port: Int, tries: Int): String {
            return try {
                IpScanner.scan(ipsJson ?: "[]", port, tries)
            } catch (t: Throwable) {
                try { org.json.JSONObject().put("ok", false).put("error", t.message ?: "scan failed").toString() }
                catch (_: Throwable) { "{\"ok\":false,\"error\":\"scan failed\"}" }
            }
        }

        // ---------- 🏷️ اطلاعات آفلاین IP (کشور/ASN از دادهٔ واقعی همراه اپ) ----------
        private val geoLock = Object()
        @Volatile private var geoState = 0 // 0=نالود، 1=در حال بارگذاری، 2=آماده

        private fun ensureGeo() {
            if (geoState == 2) return
            synchronized(geoLock) {
                if (geoState == 2) return
                geoState = 1
                try {
                    // AGP فایل‌های .gz را هنگام بسته‌بندی باز می‌کند؛ پس هر دو نام را امتحان می‌کنیم.
                    fun openAny(base: String): java.io.InputStream {
                        try {
                            return assets.open(base)
                        } catch (_: Throwable) {
                            val raw = assets.open(base + ".gz")
                            return java.util.zip.GZIPInputStream(raw, 1 shl 20)
                        }
                    }
                    openAny("data/ip2asn-v4.tsv").use { IpTable.loadIp2asn(it, false) }
                    openAny("data/ip2asn-v6.tsv").use { IpTable.loadIp2asn(it, true) }
                    openAny("data/dbip-country.csv").use { IpTable.loadDbipCsv(it) }
                    geoState = 2
                } catch (t: Throwable) {
                    geoState = 0
                }
            }
        }

        /** برای چند IP: کشور (GeoIP + BGP)، ASN، سازمان، بازهٔ اعلام‌شده — کاملاً آفلاین. */
        @JavascriptInterface
        fun geoInfo(ipsJson: String?): String {
            return try {
                ensureGeo()
                val arr = org.json.JSONArray(ipsJson ?: "[]")
                val out = org.json.JSONArray()
                var i = 0
                while (i < arr.length() && i < 128) {
                    val ip = arr.optString(i, "").trim()
                    i++
                    if (ip.isEmpty()) continue
                    val row = IpTable.lookup(ip)
                    val o = org.json.JSONObject().put("ip", ip)
                    for (k in row.keys) o.put(k, row[k])
                    out.put(o)
                }
                org.json.JSONObject().put("ok", geoState == 2)
                    .put("rows", out).put("ready", IpTable.loaded)
                    .put("v4_ranges", IpTable.rowsV4).put("v6_ranges", IpTable.rowsV6)
                    .put("geo_ranges", IpTable.rowsGeo).toString()
            } catch (t: Throwable) {
                "{\"ok\":false,\"error\":\"" + (t.message ?: "geo failed").replace("\"", "") + "\"}"
            }
        }

        /** خودآزمون دیتابیس روی IPهای شناخته‌شده — نتیجه در UI نشان داده می‌شود. */
        @JavascriptInterface
        fun geoTest(): String {
            return try { ensureGeo(); IpTable.selfTest() } catch (t: Throwable) { "{\"pass\":0,\"total\":5,\"head\":\"بارگذاری دیتابیس ناموفق\",\"lines\":[]}" }
        }

        /** فهرست رزولورهای واقعی همراه اپ (trickest/resolvers) — ۱۰٬۸۹۳ مورد. */
        @JavascriptInterface
        fun realResolvers(sampleCount: Int, interval: Int): String {
            return try {
                val lines = assets.open("data/resolvers-real.txt").bufferedReader().use { it.readLines() }
                val step = if (interval > 0) interval else 1
                val out = org.json.JSONArray()
                var i = 0
                while (i < lines.size && out.length() < sampleCount) {
                    val v = lines[i].trim()
                    if (v.isNotEmpty()) out.put(v)
                    i += step
                }
                org.json.JSONObject().put("ok", true).put("total", lines.size).put("ips", out).toString()
            } catch (t: Throwable) { "{\"ok\":false,\"error\":\"resolver list\"}" }
        }

        /** وصل‌شدن از داخل صفحهٔ وب به یک رزولور مشخص. */
        @JavascriptInterface
        fun startDns(id: String?, fa: String?, ips: String?, dotHost: String?, sni: String?, extraRoutes: Boolean): Boolean {
            return try {
                val list = (ips ?: "").split(',').map { it.trim() }.filter { it.isNotEmpty() }
                if (list.isEmpty()) return false
                val r = Resolver(id ?: "custom", fa ?: "رزولور", fa ?: "", "global", null, list, emptyList(), null, dotHost, sni)
                DnsPrefs.save(this@MainActivity, r)
                val i = Intent(this@MainActivity, DnsVpnService::class.java).apply {
                    action = DnsVpnService.ACTION_START
                    putExtra(DnsVpnService.EXTRA_ID, r.id)
                    putExtra(DnsVpnService.EXTRA_FA, r.fa)
                    putExtra(DnsVpnService.EXTRA_IPS, list.joinToString(","))
                    putExtra(DnsVpnService.EXTRA_DOT, dotHost)
                    putExtra(DnsVpnService.EXTRA_SNI, sni)
                    putExtra(DnsVpnService.EXTRA_EXTRA_ROUTES, extraRoutes)
                }
                val prep = android.net.VpnService.prepare(this@MainActivity)
                if (prep != null) { startActivity(prep); true }
                else { androidx.core.content.ContextCompat.startForegroundService(this@MainActivity, i); true }
            } catch (t: Throwable) { false }
        }

        @JavascriptInterface
        fun stopDns(): Boolean {
            return try {
                startService(Intent(this@MainActivity, DnsVpnService::class.java).setAction(DnsVpnService.ACTION_STOP)); true
            } catch (t: Throwable) { false }
        }
    }

}
