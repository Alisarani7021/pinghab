package ir.dnsradar.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/**
 * «حالت DNS روی گوشی» — تغییردهندهٔ DNS بدون روت.
 *
 * این سرویس، VPN نیست به معنای عبور ترافیک از سرور ما:
 *  ۱) فقط بسته‌های DNS (به سرورهای DNS فعلی همان شبکه، پورت ۵۳) از تونل محلی رد می‌شوند؛
 *  ۲) همین‌جا روی خود گوشی با DoT (یا UDP برای رزولور بومی ایران) به رزولور انتخابی فرستاده می‌شوند؛
 *  ۳) هیچ بایتی از ترافیک بازی/مرور به سرور ما یا جای دیگری نمی‌رود. ترافیک غیر-DNS دست‌نخورده می‌ماند.
 *
 * صادقانه: اگر «Private DNS» سیستم روشن باشد، کوئری‌ها رمزنگاری‌شده‌اند و از این مسیر رد نمی‌شوند؛
 * خودِ اپ همین را می‌گوید و راه خاموش‌کردنش را نشان می‌دهد.
 */
class DnsVpnService : VpnService() {

    companion object {
        const val ACTION_START = "ir.dnsradar.app.DNS_START"
        const val ACTION_STOP = "ir.dnsradar.app.DNS_STOP"
        const val EXTRA_FA = "fa"
        const val EXTRA_NAME = "name"
        const val EXTRA_ID = "id"
        const val EXTRA_IPS = "ips"          // با کاما جدا
        const val EXTRA_DOT = "dot"
        const val EXTRA_SNI = "sni"
        const val EXTRA_KIND = "kind"
        const val EXTRA_EXTRA_ROUTES = "extra_routes"   // 1 = 8.8.8.8/1.1.1.1 هم گرفته شود
        private const val NOTIF_ID = 50410
        private const val CHANNEL = "ph_dns"

        @Volatile var running = false
        @Volatile var label: String = ""
        @Volatile var since: Long = 0
        @Volatile var lastError: String? = null

        private val sent = AtomicInteger(0)
        private val answered = AtomicInteger(0)
        private val failed = AtomicInteger(0)
        private val rtts = ArrayList<Int>()
        @Volatile private var lastRtt = -1

        data class Snap(
            val running: Boolean, val label: String, val since: Long, val sent: Int, val answered: Int,
            val failed: Int, val lossPct: Int, val lastRtt: Int?, val avgRtt: Int?, val jitter: Int?, val error: String?
        )

        fun snapshot(): Snap {
            val s = sent.get(); val a = answered.get(); val f = failed.get()
            val arr = synchronized(rtts) { rtts.toList() }
            val avg = if (arr.isEmpty()) null else arr.average().toInt()
            var jit: Int? = null
            if (arr.size > 1) {
                var sum = 0
                for (i in 1 until arr.size) sum += kotlin.math.abs(arr[i] - arr[i - 1])
                jit = sum / (arr.size - 1)
            }
            return Snap(running, label, since, s, a, f, if (s > 0) f * 100 / s else 0, lastRtt.takeIf { it >= 0 }, avg, jit, lastError)
        }

        fun resetStats() {
            sent.set(0); answered.set(0); failed.set(0); lastRtt = -1
            synchronized(rtts) { rtts.clear() }
        }
    }

    private var tun: ParcelFileDescriptor? = null
    private var thread: Thread? = null
    private val pool = Executors.newFixedThreadPool(3)
    @Volatile private var stopFlag = false
    @Volatile private var resolver: Resolver? = null
    private val writeLock = Any()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { shutdown(); return START_NOT_STICKY }
            ACTION_START -> {
                val ips = (intent.getStringExtra(EXTRA_IPS) ?: "").split(',').map { it.trim() }.filter { it.isNotEmpty() }
                resolver = Resolver(
                    id = intent.getStringExtra(EXTRA_ID) ?: "custom",
                    fa = intent.getStringExtra(EXTRA_FA) ?: "رزولور",
                    name = intent.getStringExtra(EXTRA_NAME) ?: "",
                    kind = intent.getStringExtra(EXTRA_KIND) ?: "global",
                    cc = null, ips = ips, dot = intent.getStringExtra(EXTRA_DOT), sni = intent.getStringExtra(EXTRA_SNI)
                )
                label = resolver?.fa ?: ""
                lastError = null
                startFg()
                startTunnel(intent.getBooleanExtra(EXTRA_EXTRA_ROUTES, false))
            }
            else -> { if (!running) { shutdown() } }
        }
        return START_NOT_STICKY
    }

    private fun startFg() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            val ch = NotificationChannel(CHANNEL, "حالت DNS", NotificationManager.IMPORTANCE_LOW)
            ch.description = "نمایش وضعیت تغییر DNS روی این گوشی"
            nm.createNotificationChannel(ch)
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, DnsChangerActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop = PendingIntent.getService(this, 1,
            Intent(this, DnsVpnService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE)
        val notif: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("پینگ‌هاب — حالت DNS روشن است")
            .setContentText("رزولور: ${resolver?.fa ?: "—"} · فقط DNS، نه VPN ترافیک")
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setOngoing(true)
            .setContentIntent(open)
            .addAction(0, "قطع", stop)
            .build()
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
                   else if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0
        try { ServiceCompat.startForeground(this, NOTIF_ID, notif, type) }
        catch (t: Throwable) {
            lastError = "اعلان سرویس ثبت نشد: ${t.message}"
            try { startForeground(NOTIF_ID, notif) } catch (_: Throwable) {}
        }
    }

    private fun dnsServersToIntercept(): List<String> {
        val out = LinkedHashSet<String>()
        try {
            val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val lp = cm.getLinkProperties(cm.activeNetwork)
            lp?.dnsServers?.forEach { a -> a.hostAddress?.let { if (!it.contains(':')) out.add(it) } }
        } catch (_: Throwable) {}
        if (out.isEmpty()) { out.add("8.8.8.8"); out.add("1.1.1.1") }
        return out.toList()
    }

    private fun startTunnel(extraRoutes: Boolean) {
        if (running) { return }
        val r = resolver ?: return
        val chosen = r.ip ?: return
        try {
            val b = Builder()
                .setSession("پینگ‌هاب — حالت DNS")
                .setMetered(false)
                .addAddress("10.111.222.2", 32)
            // فقط سرورهای DNS همین شبکه از تونل محلی رد می‌شوند (روش استاندارد تغییردهندهٔ DNS)
            for (ip in dnsServersToIntercept()) {
                try { b.addRoute(ip, 32) } catch (_: Throwable) {}
            }
            if (extraRoutes) {
                for (ip in listOf("8.8.8.8", "8.8.4.4", "1.1.1.1")) {
                    try { b.addRoute(ip, 32) } catch (_: Throwable) {}
                }
            }
            try {
                val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
                cm.activeNetwork?.let { b.setUnderlyingNetworks(arrayOf(it)) }
            } catch (_: Throwable) {}

            tun = b.establish()
            if (tun == null) { lastError = "اجازهٔ تونل محلی داده نشد"; running = false; return }
            resetStats(); running = true; since = System.currentTimeMillis()
            DnsProbe.protector = { s -> try { protect(s) } catch (_: Throwable) { false } }
            DnsProbe.datagramProtector = { s -> try { protect(s) } catch (_: Throwable) { false } }
            stopFlag = false
            thread = Thread({ loop(r, chosen) }, "ph-dns-loop").also { it.start() }
        } catch (t: Throwable) {
            lastError = "شروع تونل محلی ناموفق: ${t.message}"
            running = false
        }
    }

    private fun loop(r: Resolver, chosen: String) {
        val pfd = tun ?: return
        val input = FileInputStream(pfd.fileDescriptor)
        val output = FileOutputStream(pfd.fileDescriptor)
        val buf = ByteArray(32767)
        while (!stopFlag) {
            val n = try { input.read(buf) } catch (t: Throwable) { -1 }
            if (n <= 0) break          // EOF/بسته‌شدن تونل: چرخه را تمام کن (وگرنه پردازنده می‌سوزد)
            try { handlePacket(buf, n, r, chosen, output) } catch (_: Throwable) {}
        }
        try { input.close() } catch (_: Throwable) {}
        try { output.close() } catch (_: Throwable) {}
        running = false
    }

    /** یک بستهٔ IPv4 را می‌خواند؛ اگر DNS بود، پاسخش را همان‌جا می‌سازد و برمی‌گرداند. */
    private fun handlePacket(p: ByteArray, len: Int, r: Resolver, chosen: String, out: FileOutputStream) {
        if (len < 28) return
        val v = (p[0].toInt() and 0xf0) shr 4
        if (v != 4) return
        val ihl = (p[0].toInt() and 0x0f) * 4
        if (ihl < 20 || len < ihl + 8) return
        val proto = p[9].toInt() and 0xff
        val srcIp = p.copyOfRange(12, 16)
        val dstIp = p.copyOfRange(16, 20)

        if (proto == 17) {                                  // UDP
            val srcPort = ((p[ihl].toInt() and 0xff) shl 8) or (p[ihl + 1].toInt() and 0xff)
            val dstPort = ((p[ihl + 2].toInt() and 0xff) shl 8) or (p[ihl + 3].toInt() and 0xff)
            if (dstPort != 53) return                        // ترافیک غیر-DNS را دست نمی‌زنیم
            val qLen = ((p[ihl + 4].toInt() and 0xff) shl 8) or (p[ihl + 5].toInt() and 0xff)
            val qEnd = (ihl + qLen).coerceAtMost(len)
            if (qEnd <= ihl + 8) return
            val query = p.copyOfRange(ihl + 8, qEnd)
            sent.incrementAndGet()
            pool.submit {
                val t0 = System.nanoTime()
                val resp = DnsProbe.query(r, nameFrom(query), 5000)
                val dt = ((System.nanoTime() - t0) / 1_000_000L).toInt()
                if (resp != null && DnsQuery.rcode(resp) == 0) {
                    answered.incrementAndGet(); lastRtt = dt
                    synchronized(rtts) { rtts.add(dt); if (rtts.size > 40) rtts.removeAt(0) }
                    val pkt = buildUdpReply(srcIp, srcPort, dstIp, dstPort, resp)
                    synchronized(writeLock) { try { out.write(pkt) } catch (_: Throwable) {} }
                } else {
                    failed.incrementAndGet()
                }
            }
        } else if (proto == 6) {                             // TCP به همان سرورها: سریع رد کن، معلق نگذار
            val srcPort = ((p[ihl].toInt() and 0xff) shl 8) or (p[ihl + 1].toInt() and 0xff)
            val dstPort = ((p[ihl + 2].toInt() and 0xff) shl 8) or (p[ihl + 3].toInt() and 0xff)
            if (dstPort != 53) return
            val seq = readInt32(p, ihl + 4)
            val pkt = buildTcpReset(srcIp, srcPort, dstIp, dstPort, seq)
            synchronized(writeLock) { try { out.write(pkt) } catch (_: Throwable) {} }
        }
    }

    private fun nameFrom(query: ByteArray): String {
        return try {
            var i = 12; val sb = StringBuilder()
            while (i < query.size && query[i].toInt() != 0) {
                val l = query[i].toInt() and 0xff
                if (l > 63 || i + 1 + l > query.size) break
                if (sb.isNotEmpty()) sb.append('.')
                sb.append(String(query, i + 1, l, Charsets.US_ASCII))
                i += 1 + l
            }
            val s = sb.toString().ifEmpty { "www.wikipedia.org" }
            s
        } catch (_: Throwable) { "www.wikipedia.org" }
    }

    private fun readInt32(p: ByteArray, off: Int): Long {
        var v = 0L
        for (i in 0 until 4) v = (v shl 8) or (p[off + i].toLong() and 0xff)
        return v
    }

    private fun ipChecksum(h: ByteArray): Int {
        var sum = 0L; var i = 0
        while (i + 1 < h.size) { sum += (((h[i].toInt() and 0xff) shl 8) or (h[i + 1].toInt() and 0xff)).toLong(); i += 2 }
        if (i < h.size) sum += ((h[i].toInt() and 0xff) shl 8).toLong()
        while (sum shr 16 != 0L) sum = (sum and 0xffff) + (sum shr 16)
        return (sum.inv() and 0xffff).toInt()
    }

    /** پاسخ IPv4/UDP با مبدأ و مقصد جابه‌جا (checksum UDP صفر = مجاز در IPv4). */
    private fun buildUdpReply(srcIp: ByteArray, srcPort: Int, dstIp: ByteArray, dstPort: Int, payload: ByteArray): ByteArray {
        val total = 20 + 8 + payload.size
        val pkt = ByteArray(total)
        pkt[0] = 0x45
        pkt[2] = ((total shr 8) and 0xff).toByte(); pkt[3] = (total and 0xff).toByte()
        pkt[8] = 64; pkt[9] = 17
        // مبدأ/مقصد: پاسخ از سمت سرور DNS به سمت اپ
        for (i in 0 until 4) { pkt[12 + i] = dstIp[i]; pkt[16 + i] = srcIp[i] }
        val c = ipChecksum(pkt.copyOfRange(0, 20))
        pkt[10] = ((c shr 8) and 0xff).toByte(); pkt[11] = (c and 0xff).toByte()
        pkt[20] = ((dstPort shr 8) and 0xff).toByte(); pkt[21] = (dstPort and 0xff).toByte()
        pkt[22] = ((srcPort shr 8) and 0xff).toByte(); pkt[23] = (srcPort and 0xff).toByte()
        val ulen = 8 + payload.size
        pkt[24] = ((ulen shr 8) and 0xff).toByte(); pkt[25] = (ulen and 0xff).toByte()
        pkt[26] = 0; pkt[27] = 0
        System.arraycopy(payload, 0, pkt, 28, payload.size)
        return pkt
    }

    /** RST برای TCP به سرورهای DNS: «سریع رد شود» بهتر از «معلق بماند». */
    private fun buildTcpReset(srcIp: ByteArray, srcPort: Int, dstIp: ByteArray, dstPort: Int, theirSeq: Long): ByteArray {
        val total = 40
        val pkt = ByteArray(total)
        pkt[0] = 0x45
        pkt[2] = ((total shr 8) and 0xff).toByte(); pkt[3] = (total and 0xff).toByte()
        pkt[8] = 64; pkt[9] = 6
        // بستهٔ پاسخ: مبدأ = سرور DNS، مقصد = اپ
        for (i in 0 until 4) { pkt[12 + i] = dstIp[i]; pkt[16 + i] = srcIp[i] }
        val ipc = ipChecksum(pkt.copyOfRange(0, 20))
        pkt[10] = ((ipc shr 8) and 0xff).toByte(); pkt[11] = (ipc and 0xff).toByte()

        val seg = ByteArray(20)
        seg[0] = ((dstPort shr 8) and 0xff).toByte(); seg[1] = (dstPort and 0xff).toByte()
        seg[2] = ((srcPort shr 8) and 0xff).toByte(); seg[3] = (srcPort and 0xff).toByte()
        val ack = theirSeq + 1
        for (i in 0 until 4) seg[8 + i] = ((ack shr (8 * (3 - i))) and 0xff).toByte()
        seg[12] = 0x50                    // data offset = 5 word
        seg[13] = 0x14                    // RST|ACK
        // شبه‌سرصفحه: IP مبدأ + IP مقصد + صفر + پروتکل + طول TCP
        val pseudo = ByteArray(12 + seg.size)
        for (i in 0 until 4) { pseudo[i] = pkt[12 + i]; pseudo[4 + i] = pkt[16 + i] }
        pseudo[9] = 6
        pseudo[10] = ((seg.size shr 8) and 0xff).toByte(); pseudo[11] = (seg.size and 0xff).toByte()
        System.arraycopy(seg, 0, pseudo, 12, seg.size)
        val ck = ipChecksum(pseudo)
        seg[16] = ((ck shr 8) and 0xff).toByte(); seg[17] = (ck and 0xff).toByte()
        System.arraycopy(seg, 0, pkt, 20, seg.size)
        return pkt
    }

    private fun shutdown() {
        stopFlag = true
        running = false
        DnsProbe.protector = null
        DnsProbe.datagramProtector = null
        try { thread?.interrupt() } catch (_: Throwable) {}
        thread = null
        try { tun?.close() } catch (_: Throwable) {}
        tun = null
        try { ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE) } catch (_: Throwable) {}
        try { stopSelf() } catch (_: Throwable) {}
    }

    override fun onRevoke() { shutdown() }

    override fun onDestroy() {
        stopFlag = true; running = false
        try { tun?.close() } catch (_: Throwable) {}
        super.onDestroy()
    }
}

/** ابزار: نگه‌داشتن انتخاب کاربر بین اجراها (فقط همین — بدون دادهٔ شناسایی‌کننده). */
object DnsPrefs {
    private const val FILE = "ph_dns"
    fun save(ctx: Context, r: Resolver) {
        val e = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit()
        e.putString("id", r.id); e.putString("fa", r.fa); e.putString("name", r.name)
        e.putString("ips", r.ips.joinToString(",")); e.putString("dot", r.dotHost)
        e.putString("kind", r.kind); e.apply()
    }
    fun load(ctx: Context): Resolver? {
        val p = ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE)
        val id = p.getString("id", null) ?: return null
        val ips = (p.getString("ips", "") ?: "").split(',').map { it.trim() }.filter { it.isNotEmpty() }
        if (ips.isEmpty()) return null
        return Resolver(id, p.getString("fa", "") ?: id, p.getString("name", "") ?: "",
            p.getString("kind", "global") ?: "global", null, ips, emptyList(),
            null, p.getString("dot", null))
    }
}
