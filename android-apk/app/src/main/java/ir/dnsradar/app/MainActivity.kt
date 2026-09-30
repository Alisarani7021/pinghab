package ir.dnsradar.app

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Bundle
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
}
