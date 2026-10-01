package ir.dnsradar.app

import org.json.JSONArray
import org.json.JSONObject
import java.net.InetAddress
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.abs

/**
 * اسکنر IP و DNS «پینگ‌هاب» — سنجش واقعی از خط خودِ گوشی.
 *
 * چه چیزی را می‌سنجیم (و چه چیزی را نه):
 *  • UDP/53 : پرس‌وجوی DNS واقعی روی پورت ۵۳ → زمان رفت‌وبرگشت و افت.
 *  • TCP/port: زمان برقراری اتصال TCP (پیش‌فرض ۵۳، قابل تغییر به ۴۴۳/۸۰).
 *  • ICMP در اندروید بدون روت از داخل WebView در دسترس نیست؛ به‌جای عدد ساختگی،
 *    همان دو مسیرِ واقعی را می‌سنجیم و صادقانه برچسب می‌زنیم.
 *
 * قواعد ثابت: هیچ محتوایی از ترافیک ذخیره نمی‌شود؛ فقط زمان و شمارش. «کاندید، نه توصیه».
 */
object IpScanner {

    private const val MAX_IPS = 64
    private const val TIMEOUT_MS = 1500

    private data class Stat(val ok: Int, val tries: Int, val min: Int?, val avg: Int?, val jitter: Int?, val loss: Int, val ms: List<Int>)

    private fun statOf(ms: List<Int>, tries: Int): Stat {
        if (ms.isEmpty()) return Stat(0, tries, null, null, null, 100, emptyList())
        val sorted = ms.sorted()
        val avg = Math.round(sorted.average()).toInt()
        var j = 0
        if (sorted.size > 1) {
            var sum = 0
            for (i in 1 until sorted.size) sum += abs(sorted[i] - sorted[i - 1])
            j = sum / (sorted.size - 1)
        }
        return Stat(sorted.size, tries, sorted.first(), avg, j, ((tries - sorted.size) * 100) / tries, sorted)
    }

    private fun toJson(s: Stat): JSONObject = JSONObject()
        .put("ok", s.ok).put("tries", s.tries)
        .put("min", s.min ?: -1).put("avg", s.avg ?: -1).put("jitter", s.jitter ?: -1)
        .put("loss", s.loss).put("ms", JSONArray(s.ms))

    private fun probeUdp(ip: String, name: String, tries: Int): Stat {
        val q = DnsQuery.buildA(name)
        val ms = ArrayList<Int>(tries)
        for (i in 0 until tries) {
            val t0 = System.nanoTime()
            val resp = try { DnsProbe.udp(ip, q, TIMEOUT_MS) } catch (_: Throwable) { null }
            val dt = ((System.nanoTime() - t0) / 1_000_000L).toInt()
            if (resp != null && resp.size >= 12) ms.add(dt)
        }
        return statOf(ms, tries)
    }

    private fun probeTcp(ip: String, port: Int, tries: Int): Stat {
        val ms = ArrayList<Int>(tries)
        for (i in 0 until tries) {
            val r = DnsProbe.tcpRtt(ip, port, TIMEOUT_MS)
            if (r != null) ms.add(r)
        }
        return statOf(ms, tries)
    }

    private fun looksIpv4(s: String) = Regex("^\\d{1,3}(\\.\\d{1,3}){3}$").matches(s)
    private fun looksIpv6(s: String) = s.contains(":") && Regex("^[0-9a-fA-F:]+$").matches(s)

    /** ورودی: JSON آرایهٔ رشته‌ها (IP یا دامنه). خروجی: JSON نتیجهٔ کامل. */
    fun scan(ipsJson: String, portIn: Int, triesIn: Int): String {
        val port = if (portIn in 1..65535) portIn else 53
        val tries = triesIn.coerceIn(1, 6)
        val list = ArrayList<String>()
        try {
            val arr = JSONArray(ipsJson)
            var i = 0
            while (i < arr.length() && list.size < MAX_IPS) {
                val v = arr.optString(i, "").trim()
                if (v.isNotEmpty()) list.add(v)
                i++
            }
        } catch (_: Throwable) { /* فهرست خالی */ }
        if (list.isEmpty()) return JSONObject().put("ok", false).put("error", "فهرست هدف‌ها خالی است").toString()

        val out = JSONArray()
        val pool = Executors.newFixedThreadPool(8)
        try {
            val futures = list.map { target ->
                pool.submit<JSONObject> {
                    val row = JSONObject().put("target", target).put("port", port)
                    var ip = target
                    if (!looksIpv4(target) && !looksIpv6(target)) {
                        val resolved = try { InetAddress.getByName(target).hostAddress } catch (_: Throwable) { null }
                        if (resolved == null) return@submit row.put("ok", false).put("error", "دامنه حل نشد")
                        row.put("host_note", "دامنه به $resolved حل شد (DNS دستگاه)")
                        ip = resolved
                    }
                    row.put("ip", ip).put("version", if (ip.contains(":")) "v6" else "v4")
                    // لمسی به هدف تا DNS سیستم کش نکند و هر نمونه واقعی باشد
                    val udp = probeUdp(ip, "example.com", tries)
                    val tcp = probeTcp(ip, port, tries)
                    row.put("udp", toJson(udp)).put("tcp", toJson(tcp))
                    val dnsOk = udp.ok > 0
                    row.put("ok", true)
                    row.put("verdict_fa", when {
                        dnsOk && udp.avg!! <= 80 -> "عالی"
                        dnsOk && udp.avg!! <= 180 -> "خوب"
                        dnsOk && udp.avg!! <= 400 -> "قابل قبول"
                        dnsOk -> "کند"
                        tcp.ok > 0 -> "DNS بی‌پاسخ · TCP پاسخ داد"
                        else -> "بی‌پاسخ"
                    })
                    row
                }
            }
            for (f in futures) {
                try { out.put(f.get(25, TimeUnit.SECONDS)) }
                catch (_: Throwable) { /* رد شد */ }
            }
        } finally {
            pool.shutdownNow()
        }
        return JSONObject()
            .put("ok", true).put("at", System.currentTimeMillis())
            .put("rows", out).put("count", out.length())
            .put("port", port).put("tries", tries)
            .put("note", "سنجش از خط خودِ گوشی: UDP/53 و TCP/$port. ICMP بدون روت در اندروید در دسترس نیست — عدد ساختگی نمی‌سازیم.")
            .toString()
    }
}
