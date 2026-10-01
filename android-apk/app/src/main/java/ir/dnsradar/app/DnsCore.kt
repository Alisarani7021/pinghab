package ir.dnsradar.app

import android.os.Build
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import javax.net.ssl.SNIHostName
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

/**
 * هستهٔ DNS «پینگ‌هاب» — ساخت/خواندن پیام DNS و سنجش رزولورها.
 *
 * قواعد ثابت پروژه در این فایل:
 *  • هیچ داده‌ای از محتوای کوئری‌ها ذخیره نمی‌شود؛ فقط شمارش و زمان نگه داشته می‌شود.
 *  • «قهرمان» اعلام نمی‌کنیم: این‌ها کاندیدند؛ عدد واقعی روی خط کاربر سنجیده می‌شود.
 *  • DNS پینگ داخل مچ بازی را کم نمی‌کند؛ فقط زمان اتصال/نام‌یابی را بهتر می‌کند.
 */

data class Resolver(
    val id: String,
    val fa: String,
    val name: String,
    val kind: String,            // global | iran | national
    val cc: String?,
    val ips: List<String>,
    val ipv6: List<String> = emptyList(),
    val doh: String? = null,
    val dot: String? = null,
    val sni: String? = null,
    val note: String = "",
    val verified: Boolean = false,
) {
    /** میزبان TLS برای DoT: اگر dot اعلام نشده، از sni یا نام سرویس استفاده می‌شود. */
    val dotHost: String? get() = dot ?: sni
    val ip: String? get() = ips.firstOrNull()
}

object DnsQuery {
    /** یک کوئری A ساده می‌سازد (بدون EDNS — سازگارترین حالت با همهٔ رزولورها). */
    fun buildA(name: String, id: Int = 0x5048): ByteArray {
        val out = ByteArrayOutputStream(64)
        fun w16(v: Int) { out.write((v shr 8) and 0xff); out.write(v and 0xff) }
        w16(id); w16(0x0100); w16(1); w16(0); w16(0); w16(0)
        for (part in name.trim('.').split('.')) {
            val b = part.toByteArray(Charsets.US_ASCII)
            out.write(b.size.coerceAtMost(63)); out.write(b)
        }
        out.write(0); w16(1); w16(1)
        return out.toByteArray()
    }

    fun rcode(resp: ByteArray?): Int? =
        if (resp == null || resp.size < 12) null else resp[3].toInt() and 0x0f

    fun answers(resp: ByteArray?): Int =
        if (resp == null || resp.size < 12) 0 else (((resp[6].toInt() and 0xff) shl 8) or (resp[7].toInt() and 0xff))
}

object DnsProbe {
    /** سوکت‌هایی که خودمان می‌سازیم باید از تونل مستثنا شوند (VpnService.protect). */
    @Volatile var protector: ((Socket) -> Boolean)? = null
    @Volatile var datagramProtector: ((DatagramSocket) -> Boolean)? = null

    private fun readN(input: InputStream, n: Int): ByteArray {
        val buf = ByteArray(n); var off = 0
        while (off < n) {
            val r = input.read(buf, off, n - off)
            if (r < 0) throw java.io.EOFException("بستهٔ ناتمام")
            off += r
        }
        return buf
    }

    /** کوئری روی DNS-over-TLS (پورت ۸۵۳) — مسیر پیشنهادی: رمزنگاری‌شده و قابل‌قاپیدن نیست. */
    fun dot(ip: String, host: String, query: ByteArray, timeoutMs: Int = 4000): ByteArray {
        val raw = Socket()
        try {
            protector?.invoke(raw)
            raw.tcpNoDelay = true
            raw.connect(InetSocketAddress(ip, 853), timeoutMs)
            val ssl = (SSLSocketFactory.getDefault() as SSLSocketFactory)
                .createSocket(raw, host, 853, true) as SSLSocket
            try {
                if (Build.VERSION.SDK_INT >= 24) {
                    val p = ssl.sslParameters
                    p.serverNames = listOf(SNIHostName(host))
                    try { p.endpointIdentificationAlgorithm = "HTTPS" } catch (_: Throwable) {}
                    ssl.sslParameters = p
                }
            } catch (_: Throwable) {}
            ssl.soTimeout = timeoutMs
            ssl.startHandshake()
            val o = ssl.outputStream
            o.write(byteArrayOf(((query.size shr 8) and 0xff).toByte(), (query.size and 0xff).toByte()))
            o.write(query); o.flush()
            val len = ((readN(ssl.inputStream, 1)[0].toInt() and 0xff) shl 8) or (readN(ssl.inputStream, 1)[0].toInt() and 0xff)
            if (len <= 0 || len > 8192) throw java.io.IOException("طول پاسخ نامعتبر")
            return readN(ssl.inputStream, len)
        } finally {
            try { raw.close() } catch (_: Throwable) {}
        }
    }

    /** کوئری روی UDP کلاسیک (پورت ۵۳) — برای رزولورهای بومی ایران که DoT ندارند. */
    fun udp(ip: String, query: ByteArray, timeoutMs: Int = 3000): ByteArray {
        val s = DatagramSocket()
        try {
            datagramProtector?.invoke(s)
            s.soTimeout = timeoutMs
            s.send(DatagramPacket(query, query.size, InetAddress.getByName(ip), 53))
            val buf = ByteArray(4096)
            val p = DatagramPacket(buf, buf.size)
            s.receive(p)
            return buf.copyOf(p.length)
        } finally {
            try { s.close() } catch (_: Throwable) {}
        }
    }

    /** یک پرس‌وجوی کامل با بهترین روش موجود برای این رزولور. */
    fun query(r: Resolver, name: String = "www.wikipedia.org", timeoutMs: Int = 4000): ByteArray? {
        val ip = r.ip ?: return null
        val q = DnsQuery.buildA(name)
        return try {
            val host = r.dotHost
            if (host != null) {
                try { dot(ip, host, q, timeoutMs) } catch (_: Throwable) { udp(ip, q, timeoutMs) }
            } else udp(ip, q, timeoutMs)
        } catch (_: Throwable) { null }
    }

    data class Measure(val ok: Int, val total: Int, val p50: Int?, val jitter: Int?, val lossPct: Int, val method: String, val ms: List<Int>)

    /** سنجش چندبارهٔ یک رزولور: میانه، نوسان، افت + روشِ استفاده‌شده. */
    fun measure(r: Resolver, tries: Int = 3, name: String = "www.wikipedia.org"): Measure {
        val ms = ArrayList<Int>(tries)
        val useDot = r.dotHost != null
        for (i in 0 until tries) {
            val t0 = System.nanoTime()
            val resp = query(r, name)
            val dt = ((System.nanoTime() - t0) / 1_000_000L).toInt()
            if (resp != null && DnsQuery.rcode(resp) == 0) ms.add(dt)
        }
        val sorted = ms.sorted()
        val p50 = if (sorted.isEmpty()) null else sorted[sorted.size / 2]
        val jit = if (sorted.size > 1) {
            var s = 0; for (i in 1 until sorted.size) s += kotlin.math.abs(sorted[i] - sorted[i - 1])
            s / (sorted.size - 1)
        } else 0
        return Measure(ms.size, tries, p50, jit, ((tries - ms.size) * 100 / tries), if (useDot) "DoT" else "UDP", ms)
    }

    /** زمان دست‌دادن TCP (پینگ سبک برای هاست‌های بازی که ICMP را می‌بندند). */
    fun tcpRtt(host: String, port: Int = 443, timeoutMs: Int = 2500): Int? {
        return try {
            val s = Socket()
            protector?.invoke(s)
            val t0 = System.nanoTime()
            s.connect(InetSocketAddress(host, port), timeoutMs)
            val dt = ((System.nanoTime() - t0) / 1_000_000L).toInt()
            try { s.close() } catch (_: Throwable) {}
            dt
        } catch (_: Throwable) { null }
    }
}
