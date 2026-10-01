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
        fun version(): String = "2.1"
    }

}
