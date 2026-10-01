package ir.dnsradar.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.telephony.TelephonyManager
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * «حالت DNS روی گوشی» — تغییردهندهٔ DNS بدون روت + داشبورد زنده.
 *
 * این صفحه سه کار می‌کند:
 *  ۱) وصل‌شدن به رزولور انتخابی (DoT/UDP روی خود گوشی — بدون عبور ترافیک از سرور ما)
 *  ۲) نمایش زندهٔ پینگ DNS، پکت‌لاس، نوسان، تعداد کوئری
 *  ۳) نمایش وضعیت خط (اپراتور/نوع شبکه/قدرت)، موقعیت از لبهٔ کلادفلر، پینگ شهرهای ایران و سرور بازی‌ها
 */
class DnsChangerActivity : AppCompatActivity() {

    companion object {
        const val SITE = "https://pinghab.catclient-59gk2mui.workers.dev"
        private const val REQ_VPN = 100
        private const val REQ_NOTIF = 101
        private val GAME_PKGS = mapOf(
            "pubg-mobile" to "com.tencent.ig",
            "mobile-legends" to "com.mobile.legends",
            "free-fire" to "com.dts.freefireth",
            "call-of-duty" to "com.activision.callofduty.shooter",
            "e-football" to "jp.konami.pesam",
            "roblox" to "com.roblox.client",
        )
    }

    private val io = Executors.newFixedThreadPool(4)
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var root: LinearLayout
    private lateinit var statusBox: LinearLayout
    private lateinit var infoBox: LinearLayout
    private lateinit var metricsBox: LinearLayout
    private lateinit var listBox: LinearLayout
    private lateinit var cityBox: LinearLayout
    private lateinit var gameBox: LinearLayout
    private lateinit var connectBtn: Button

    private val resolvers = ArrayList<Resolver>()
    private var selectedId: String? = null
    private var measuring = false

    private val cBg = Color.parseColor("#0b0b0b")
    private val cCard = Color.parseColor("#151515")
    private val cLine = Color.parseColor("#2e2e2e")
    private val cTx = Color.parseColor("#ffffff")
    private val cMut = Color.parseColor("#9a9a9a")
    private val cAcc = Color.parseColor("#ffc000")
    private val cGood = Color.parseColor("#34d399")
    private val cBad = Color.parseColor("#f87171")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        selectedId = DnsPrefs.load(this)?.id

        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(cBg)
            setPadding(dp(14), dp(14), dp(14), dp(28))
        }
        val scroll = ScrollView(this).apply { addView(root); setBackgroundColor(cBg) }
        setContentView(scroll)

        root.addView(title("🚀 حالت DNS روی گوشی", 22))
        root.addView(sub("بدون روت، بدون VPN ترافیکی: فقط کوئری‌های DNS روی همین گوشی به رزولور انتخابی می‌روند. " +
                "ترافیک بازی و مرور از هیچ سروری (از جمله ما) عبور نمی‌کند. «کاندید، نه توصیه» — عدد واقعی را همین‌جا بسنج."))

        statusBox = card(); root.addView(statusBox)
        metricsBox = card(); root.addView(metricsBox)
        infoBox = card(); root.addView(infoBox)

        connectBtn = Button(this).apply {
            text = "وصل شو"
            setTextColor(Color.parseColor("#000000"))
            background = GradientDrawable().apply { cornerRadius = dp(12).toFloat(); setColor(cAcc) }
            setPadding(dp(12), dp(12), dp(12), dp(12))
            setOnClickListener { toggleConnect() }
        }
        val rowBtns = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(8), 0, 0) }
        rowBtns.addView(connectBtn, lp(1f))
        rowBtns.addView(btn("🌍 سنجش همهٔ رزولورها") { measureAll() }, lp(1f))
        root.addView(rowBtns)

        val rowBtns2 = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(8), 0, 0) }
        rowBtns2.addView(btn("🏙️ پینگ رزولور از شهرهای ایران") { cities() }, lp(1f))
        rowBtns2.addView(btn("⚙️ Private DNS سیستم") { openPrivateDns() }, lp(1f))
        root.addView(rowBtns2)

        root.addView(title("رزولورها"))
        root.addView(sub("DoT (رمزنگاری‌شده) وقتی در دسترس باشد استفاده می‌شود؛ رزولورهای بومی ایران روی UDP می‌مانند. " +
                "«پینگ» = زمان کامل پاسخ DNS از همین خط، نه پینگ ICMP بازی."))
        listBox = card(); root.addView(listBox)

        root.addView(title("شهرهای ایران (پروب‌های دیتاسنتری)"))
        root.addView(sub("همین رزولور از گره‌های داخل ایران سنجیده می‌شود — عدد خط موبایل تو بالاتر است، ولی تفاوت شهرها معنادار است."))
        cityBox = card(); root.addView(cityBox)

        root.addView(title("بازی‌ها"))
        root.addView(sub("پینگ سرور بازی از داخل ایران + دکمهٔ باز کردن بازی. یادت باشد: DNS پینگ داخل مچ را کم نمی‌کند."))
        gameBox = card(); root.addView(gameBox)

        loadResolvers()
        loadWhoAmI()
        loadGames()
        refreshStatus()

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIF)
        }
    }

    // ---------------------------------------------------------------- link helpers
    private fun dp(v: Int) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt()
    private fun lp(w: Float) = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, w).apply { setMargins(dp(3), 0, dp(3), 0) }

    private fun title(t: String, size: Int = 17): TextView = TextView(this).apply {
        text = t; setTextColor(cTx); setTextSize(TypedValue.COMPLEX_UNIT_SP, size.toFloat())
        setPadding(0, dp(16), 0, dp(4))
    }
    private fun sub(t: String): TextView = TextView(this).apply {
        text = t; setTextColor(cMut); setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
        setPadding(0, 0, 0, dp(6))
    }
    private fun card(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(12), dp(12), dp(12), dp(12))
        background = GradientDrawable().apply { cornerRadius = dp(12).toFloat(); setColor(cCard); setStroke(dp(1), cLine) }
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { setMargins(0, dp(6), 0, dp(6)) }
    }
    private fun btn(t: String, f: () -> Unit): Button = Button(this).apply {
        text = t; setTextColor(cTx); setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
        background = GradientDrawable().apply { cornerRadius = dp(12).toFloat(); setColor(cCard); setStroke(dp(1), cLine) }
        setOnClickListener { f() }
    }
    private fun kv(k: String, v: String, color: Int = 0): TextView = TextView(this).apply {
        text = "$k: $v"; setTextColor(if (color != 0) color else cTx); setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        setPadding(0, dp(2), 0, dp(2))
    }

    // ---------------------------------------------------------------- connection
    private fun toggleConnect() {
        if (DnsVpnService.running) { stopDns(); return }
        val r = resolvers.firstOrNull { it.id == selectedId } ?: resolvers.firstOrNull()
        if (r == null) { toast("لیست رزولورها هنوز نیامده — یک لحظه بعد امتحان کن"); return }
        DnsPrefs.save(this, r)
        val prep = VpnService.prepare(this)
        if (prep != null) { startActivityForResult(prep, REQ_VPN); return }
        startDns(r, false)
    }

    private fun startDns(r: Resolver, extraRoutes: Boolean) {
        val i = Intent(this, DnsVpnService::class.java).apply {
            action = DnsVpnService.ACTION_START
            putExtra(DnsVpnService.EXTRA_ID, r.id)
            putExtra(DnsVpnService.EXTRA_FA, r.fa)
            putExtra(DnsVpnService.EXTRA_NAME, r.name)
            putExtra(DnsVpnService.EXTRA_IPS, r.ips.joinToString(","))
            putExtra(DnsVpnService.EXTRA_DOT, r.dotHost)
            putExtra(DnsVpnService.EXTRA_SNI, r.sni)
            putExtra(DnsVpnService.EXTRA_KIND, r.kind)
            putExtra(DnsVpnService.EXTRA_EXTRA_ROUTES, extraRoutes)
        }
        try { androidx.core.content.ContextCompat.startForegroundService(this, i) }
        catch (t: Throwable) { toast("شروع نشد: ${t.message}") }
    }

    private fun stopDns() {
        val i = Intent(this, DnsVpnService::class.java).setAction(DnsVpnService.ACTION_STOP)
        try { startService(i) } catch (_: Throwable) {}
        toast("قطع شد — DNS به حالت عادی شبکه برگشت")
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_VPN) {
            val r = resolvers.firstOrNull { it.id == selectedId } ?: resolvers.firstOrNull() ?: return
            if (resultCode == Activity.RESULT_OK) startDns(r, false)
            else toast("اجازهٔ تونل محلی داده نشد — بدون آن، اندروید اجازهٔ تغییر مسیر DNS نمی‌دهد")
        }
    }

    private fun refreshStatus() {
        ui.postDelayed({ refreshStatus() }, 900)
        val s = DnsVpnService.snapshot()
        statusBox.removeAllViews()
        statusBox.addView(kv("وضعیت", if (s.running) "🟢 روشن — " + s.label else "⚪️ خاموش", if (s.running) cGood else cMut))
        if (s.running && s.since > 0) {
            val sec = (System.currentTimeMillis() - s.since) / 1000
            statusBox.addView(kv("مدت اتصال", "${sec / 60} دقیقه و ${sec % 60} ثانیه"))
        }
        connectBtn.text = if (s.running) "⛔️ قطع کن" else "🔌 وصل شو"
        if (s.error != null) statusBox.addView(kv("خطا", s.error, cBad))

        metricsBox.removeAllViews()
        metricsBox.addView(title("📊 پینگ و کیفیت (زنده)", 15))
        metricsBox.addView(kv("پینگ DNS (آخرین)", if (s.lastRtt != null) "${s.lastRtt} ms" else "—"))
        metricsBox.addView(kv("میانگین", if (s.avgRtt != null) "${s.avgRtt} ms" else "—"))
        metricsBox.addView(kv("نوسان (جیتر)", if (s.jitter != null) "${s.jitter} ms" else "—"))
        metricsBox.addView(kv("پکت‌لاس", "${s.lossPct}٪  (پاسخ ${s.answered} از ${s.sent})", if (s.lossPct <= 2) cGood else if (s.lossPct < 15) cAcc else cBad))
        if (!s.running) metricsBox.addView(sub("وقتی «وصل شو» را بزنی، همین‌جا پینگ واقعی کوئری‌ها، پکت‌لاس و نوسان زنده نشان داده می‌شود."))
    }

    // ---------------------------------------------------------------- data
    private fun http(url: String): String? {
        return try {
            val c = URL(url).openConnection() as HttpURLConnection
            c.connectTimeout = 12000; c.readTimeout = 20000
            c.setRequestProperty("User-Agent", "Pinghab-Android/2.2")
            val body = c.inputStream.bufferedReader().use { it.readText() }
            c.disconnect(); body
        } catch (_: Throwable) { null }
    }

    private fun loadResolvers() {
        listBox.removeAllViews()
        listBox.addView(sub("در حال گرفتن لیست…"))
        io.submit {
            val raw = http("$SITE/api/changer")
            val list = ArrayList<Resolver>()
            if (raw != null) {
                try {
                    val arr = JSONObject(raw).optJSONArray("resolvers") ?: JSONArray()
                    for (i in 0 until arr.length()) {
                        val o = arr.getJSONObject(i)
                        val ips = ArrayList<String>()
                        o.optJSONArray("ips")?.let { a -> for (k in 0 until a.length()) ips.add(a.getString(k)) }
                        if (ips.isEmpty()) continue
                        list.add(Resolver(
                            id = o.optString("id"), fa = o.optString("fa"), name = o.optString("name"),
                            kind = o.optString("kind", "global"), cc = o.optString("cc").ifEmpty { null },
                            ips = ips, doh = o.optString("doh").ifEmpty { null }, dot = o.optString("dot").ifEmpty { null },
                            sni = o.optString("sni").ifEmpty { null }, note = o.optString("note"),
                            verified = o.optBoolean("verified", false)
                        ))
                    }
                } catch (_: Throwable) {}
            }
            if (list.isEmpty()) {                       // پشتیبان آفلاین
                list.add(Resolver("cloudflare", "کلودفلر", "Cloudflare", "global", null, listOf("1.1.1.1", "1.0.0.1"), emptyList(), null, "one.one.one.one", null, "بدون فیلتر", true))
                list.add(Resolver("google", "گوگل", "Google", "global", null, listOf("8.8.8.8", "8.8.4.4"), emptyList(), null, "dns.google", null, "بدون فیلتر", true))
                list.add(Resolver("radar", "رادار (ایران)", "Radar", "iran", "IR", listOf("10.202.10.10"), emptyList(), null, null, "radar.game", "بازی‌محور", true))
                list.add(Resolver("shecan", "شکن (ایران)", "Shecan", "iran", "IR", listOf("178.22.122.100"), emptyList(), null, null, "shecan.ir", "", true))
            }
            ui.post {
                resolvers.clear(); resolvers.addAll(list)
                if (selectedId == null || resolvers.none { it.id == selectedId }) selectedId = resolvers.firstOrNull()?.id
                renderResolvers()
            }
        }
    }

    private fun renderResolvers() {
        listBox.removeAllViews()
        for (r in resolvers) {
            val row = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, dp(6), 0, dp(6)) }
            val head = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
            val mark = TextView(this).apply {
                text = if (r.id == selectedId) "◉" else "◯"
                setTextColor(if (r.id == selectedId) cAcc else cMut); setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
                setPadding(0, 0, dp(8), 0)
            }
            head.addView(mark)
            head.addView(TextView(this).apply {
                text = r.fa; setTextColor(cTx); setTextSize(TypedValue.COMPLEX_UNIT_SP, 14.5f)
            }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            val kindFa = when (r.kind) { "iran" -> "ایران"; "national" -> "بومی"; else -> "جهانی" }
            head.addView(TextView(this).apply {
                text = kindFa; setTextColor(cMut); setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
            })
            row.addView(head)
            row.addView(TextView(this).apply {
                text = "${r.ips.first()} · ${if (r.dotHost != null) "DoT: ${r.dotHost}" else "UDP/53"}" +
                        (if (r.note.isNotEmpty()) " · ${r.note}" else "")
                setTextColor(cMut); setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            })
            val result = TextView(this).apply { setTextColor(cAcc); setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f); tag = "res-${r.id}" }
            row.addView(result)
            row.setOnClickListener {
                selectedId = r.id; DnsPrefs.save(this, r); renderResolvers()
                if (!DnsVpnService.running) toast("انتخاب شد: ${r.fa} — حالا «وصل شو»")
            }
            row.addView(View(this).apply { setBackgroundColor(cLine); layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)).apply { setMargins(0, dp(6), 0, 0) } })
            listBox.addView(row)
        }
        listBox.addView(sub("${resolvers.size} رزولور · منبع: /api/changer پینگ‌هاب (anycast جهانی + بومی ایران + رزولورهای کشوری)"))
    }

    private fun measureAll() {
        if (measuring) return
        measuring = true
        toast("سنجش ${resolvers.size} رزولور…")
        io.submit {
            for (r in resolvers) {
                val m = DnsProbe.measure(r, 3)
                ui.post {
                    (listBox.findViewWithTag<TextView>("res-${r.id}"))?.text =
                        if (m.p50 != null) "پینگ ${m.p50}ms · نوسان ${m.jitter}ms · پکت‌لاس ${m.lossPct}٪ · ${m.method}"
                        else "پاسخی نیامد — از این خط بسته است یا خیلی کند"
                }
            }
            ui.post { measuring = false; toast("سنجش تمام شد") }
        }
    }

    private fun cities() {
        val r = resolvers.firstOrNull { it.id == selectedId } ?: resolvers.firstOrNull()
        if (r?.ip == null) return
        cityBox.removeAllViews(); cityBox.addView(sub("در حال سنجش از گره‌های ایران…"))
        io.submit {
            val raw = http("$SITE/api/gameping?ips=${r.ip}&cc=IR")
            ui.post {
                cityBox.removeAllViews()
                if (raw == null) { cityBox.addView(sub("دسترسی نبود — اینترنت را چک کن")); return@post }
                try {
                    val res = JSONObject(raw).optJSONArray("results")?.optJSONObject(0)
                    val rows = res?.optJSONArray("rows")
                    if (rows == null || rows.length() == 0) { cityBox.addView(sub("پاسخی نیامد (این رزولور از ایران ICMP نمی‌گیرد)")) }
                    else {
                        cityBox.addView(kv("رزولور", r.fa))
                        for (i in 0 until rows.length()) {
                            val o = rows.getJSONObject(i)
                            val trust = o.optJSONObject("sanity")?.optBoolean("trusted", true) ?: true
                            cityBox.addView(kv(
                                "${o.optString("city")} — ${o.optString("network").take(24)}",
                                if (o.isNull("avg")) "بی‌پاسخ" else "${o.optInt("avg")}ms · لاس ${o.optInt("loss")}٪" + if (!trust) " (نانشنه)" else "",
                                if (!trust) cMut else if (o.isNull("avg")) cBad else cGood
                            ))
                        }
                    }
                    cityBox.addView(sub("پروب‌ها دیتاسنتری‌اند، نه خط موبایل تو. «نانشنه» = عددی که اثر شبکه را نشان نمی‌دهد."))
                } catch (_: Throwable) { cityBox.addView(sub("پاسخ نامعتبر")) }
            }
        }
    }

    private fun loadGames() {
        gameBox.removeAllViews(); gameBox.addView(sub("در حال گرفتن لیست بازی‌ها…"))
        io.submit {
            val raw = http("$SITE/api/games")
            ui.post {
                gameBox.removeAllViews()
                if (raw == null) { gameBox.addView(sub("دسترسی نبود")); return@post }
                try {
                    val games = JSONObject(raw).optJSONArray("games") ?: JSONArray()
                    gameBox.addView(sub("${games.length()} بازی در کاتالوگ — دکمهٔ پینگ، سرورهای هر رجین را از گره‌های ایران می‌سنجد."))
                    for (i in 0 until games.length()) {
                        val g = games.getJSONObject(i)
                        val slug = g.optString("slug")
                        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(0, dp(5), 0, dp(5)) }
                        row.addView(TextView(this).apply {
                            text = "${g.optString("fa")} · ${g.optInt("verified")}/${g.optInt("servers")} تأییدشده"
                            setTextColor(cTx); setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
                        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                        row.addView(btn("پینگ") { pingGame(slug) })
                        val pkg = GAME_PKGS[slug]
                        if (pkg != null && isInstalled(pkg)) row.addView(btn("باز کن") { launchGame(pkg) })
                        gameBox.addView(row)
                    }
                } catch (_: Throwable) { gameBox.addView(sub("پاسخ نامعتبر")) }
            }
        }
    }

    private fun isInstalled(pkg: String): Boolean = try {
        packageManager.getPackageInfo(pkg, 0); true
    } catch (_: Throwable) { false }

    private fun launchGame(pkg: String) {
        try { startActivity(packageManager.getLaunchIntentForPackage(pkg)) }
        catch (_: Throwable) { toast("باز نشد") }
    }

    private fun pingGame(slug: String) {
        toast("پینگ سرورهای ${slug}…")
        io.submit {
            val gRaw = http("$SITE/api/games?game=$slug") ?: return@submit
            val ips = ArrayList<String>()
            try {
                val regions = JSONObject(gRaw).optJSONObject("regions") ?: JSONObject()
                for (key in regions.keys()) {
                    val arr = regions.optJSONArray(key) ?: continue
                    if (arr.length() > 0) ips.add(arr.getJSONObject(0).optString("ip"))
                    if (ips.size >= 3) break
                }
            } catch (_: Throwable) {}
            if (ips.isEmpty()) { ui.post { toast("سروری برای این بازی نبود") }; return@submit }
            val raw = http("$SITE/api/gameping?ips=${ips.joinToString(",")}&cc=IR")
            ui.post {
                cityBox.removeAllViews()
                cityBox.addView(title("🎮 $slug — از گره‌های ایران", 15))
                if (raw == null) { cityBox.addView(sub("دسترسی نبود")); return@post }
                try {
                    val arr = JSONObject(raw).optJSONArray("results") ?: JSONArray()
                    for (i in 0 until arr.length()) {
                        val o = arr.getJSONObject(i)
                        val sum = o.optJSONObject("summary")
                        cityBox.addView(kv(o.optString("ip"),
                            if (sum == null || sum.isNull("median_ms")) "سنجش‌پذیر نبود (ICMP بسته)" else "میانه ${sum.optInt("median_ms")}ms · پروب معتبر ${sum.optInt("valid")}",
                            if (sum != null && !sum.isNull("median_ms") && sum.optBoolean("credible")) cGood else cMut))
                    }
                    cityBox.addView(sub("این عدد از دیتاسنترهای ایران است؛ خط موبایل تو معمولاً بالاتر. داخل بازی، عدد خودِ بازی معتبر است."))
                } catch (_: Throwable) {}
            }
        }
    }

    private fun loadWhoAmI() {
        infoBox.removeAllViews(); infoBox.addView(sub("در حال خواندن وضعیت خط…"))
        io.submit {
            val raw = http("$SITE/api/whoami")
            ui.post {
                infoBox.removeAllViews()
                infoBox.addView(title("📶 وضعیت خط و موقعیت", 15))
                val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
                val caps: NetworkCapabilities? = cm.getNetworkCapabilities(cm.activeNetwork)
                val netFa = when {
                    caps == null -> "نامعلوم"
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "WiFi"
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "دادهٔ موبایل"
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "اترنت"
                    else -> "نامعلوم"
                }
                infoBox.addView(kv("نوع شبکه", netFa))
                try {
                    val tm = getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
                    infoBox.addView(kv("اپراتور", tm.networkOperatorName.ifEmpty { "—" }))
                } catch (_: Throwable) {}
                if (caps != null) {
                    val down = caps.linkDownstreamBandwidthKbps
                    if (down > 0) infoBox.addView(kv("پهنای‌باند تخمینی لینک", "${down / 1000} Mbit/s (تخمین سیستم)"))
                    infoBox.addView(kv("اینترنت مصرفی", if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) "نامحدود/نامتر" else "مترشده"))
                }
                if (Build.VERSION.SDK_INT >= 28) {
                    try {
                        val tm = getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
                        val ss = tm.signalStrength
                        val lvl = ss?.level ?: -1
                        if (lvl >= 0) infoBox.addView(kv("قدرت سیگنال", "$lvl از ۴"))
                    } catch (_: Throwable) {}
                }
                if (raw != null) {
                    try {
                        val o = JSONObject(raw)
                        infoBox.addView(kv("موقعیت (لبهٔ کلادفلر)", "${o.optString("city")}، ${o.optString("country")} — تقریبی"))
                        infoBox.addView(kv("ASN خط تو", "${o.optString("asn")} · ${o.optString("as_org")}"))
                        infoBox.addView(kv("PoP نزدیک", o.optString("colo")))
                    } catch (_: Throwable) {}
                } else infoBox.addView(sub("موقعیت از سرور خوانده نشد (آفلاین)."))
                infoBox.addView(sub("موقعیت از لبهٔ شبکهٔ کلادفلر می‌آید و تقریبی است؛ نه GPS."))
            }
        }
    }

    private fun openPrivateDns() {
        val tries = listOf("android.settings.PRIVATE_DNS_SETTINGS", "android.settings.WIRELESS_SETTINGS")
        for (a in tries) {
            try { startActivity(Intent(a)); return } catch (_: Throwable) {}
        }
        toast("تنظیمات Private DNS روی این دستگاه پیدا نشد")
    }

    private fun toast(t: String) = Toast.makeText(this, t, Toast.LENGTH_SHORT).show()

    override fun onDestroy() {
        try { io.shutdownNow() } catch (_: Throwable) {}
        try { ui.removeCallbacksAndMessages(null) } catch (_: Throwable) {}
        super.onDestroy()
    }
}
