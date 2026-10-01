package ir.dnsradar.app

import java.io.BufferedReader
import java.io.InputStream
import java.math.BigInteger

/**
 * جدول‌های واقعی و آفلاین «پینگ‌هاب» — بدون هیچ درخواست شبکه‌ای.
 *
 * داده‌ها (همه با مجوز و منبع، داخل خودِ اپ):
 *  • ip2asn v4/v6 — iptoasn.com (دادهٔ عمومی BGP از RouteViews، Public Domain):
 *      ستون‌ها: start \t end \t asn \t cc \t org   → ASN + کشور اعلام‌شده + نام سازمان
 *  • DB-IP Country Lite (CC BY 4.0): start,end,cc  → کشور جغرافیایی هر بازه
 *  • Resolver pool — trickest/resolvers (MIT): فهرست رزولورهای عمومی واقعی
 *
 * چرا: کاربر «عدد و اطلاعات واقعی» می‌خواهد؛ پس برچسب کشور/شبکه را از داده‌های واقعی
 * می‌خوانیم، حتی وقتی اینترنت قطع است. هیچ چیزی از کاربر ذخیره/ارسال نمی‌شود.
 */
object IpTable {

    private class V4(val starts: IntArray, val ends: IntArray, val asn: IntArray, val cc: Array<String?>, val org: Array<String?>)
    private class V6(val starts: Array<BigInteger>, val ends: Array<BigInteger>, val asn: IntArray, val cc: Array<String?>, val org: Array<String?>)

    @Volatile private var v4: V4? = null
    @Volatile private var v6: V6? = null
    @Volatile private var geo: V4? = null          // DB-IP: فقط cc
    @Volatile var rowsV4 = 0; @Volatile var rowsV6 = 0; @Volatile var rowsGeo = 0

    val loaded: Boolean get() = v4 != null || geo != null

    /** IPv4 → عدد صحیح بدون علامت. */
    private fun v4ToInt(ip: String): Int? {
        val p = ip.trim().split(".")
        if (p.size != 4) return null
        var n = 0
        for (i in 0 until 4) {
            val v = p[i].toIntOrNull() ?: return null
            if (v < 0 || v > 255) return null
            n = (n shl 8) or v
        }
        return n
    }

    private fun v6ToBig(ip: String): BigInteger? {
        var s = ip.trim()
        val zone = s.indexOf('%'); if (zone >= 0) s = s.substring(0, zone)
        if (!s.contains(":")) return null
        try {
            if (s.contains("::")) {
                val side = s.split("::")
                if (side.size > 2) return null
                val h = if (side[0].isEmpty()) emptyList() else side[0].split(":")
                val t = if (side[1].isEmpty()) emptyList() else side[1].split(":")
                val g = ArrayList<String>(8)
                g.addAll(h)
                for (i in 0 until (8 - h.size - t.size)) g.add("0")
                g.addAll(t)
                s = g.joinToString(":")
            }
            val g = s.split(":")
            if (g.size != 8) return null
            var out = BigInteger.ZERO
            for (i in 0 until 8) {
                val v = g[i].ifEmpty { "0" }.toIntOrNull(16) ?: return null
                out = out.shiftLeft(16).or(BigInteger.valueOf(v.toLong()))
            }
            return out
        } catch (_: Throwable) { return null }
    }

    /** پارس جریان ip2asn (TSV) — فقط از InputStream، مناسب assets و تست JVM. */
    fun loadIp2asn(input: InputStream, v6mode: Boolean) {
        val st = ArrayList<Int>(700000); val en = ArrayList<Int>(700000)
        val asns = ArrayList<Int>(700000); val ccs = ArrayList<String?>(700000); val orgs = ArrayList<String?>(700000)
        val st6 = ArrayList<BigInteger>(200000); val en6 = ArrayList<BigInteger>(200000)
        val as6 = ArrayList<Int>(200000); val cc6 = ArrayList<String?>(200000); val or6 = ArrayList<String?>(200000)
        val br = BufferedReader(input, 1 shl 20)
        while (true) {
            val line = br.readLine() ?: break
            if (line.isEmpty()) continue
            val f = line.split('\t')
            if (f.size < 5) continue
            val a = f[2].toIntOrNull() ?: 0
            val cc = if (f[3] == "None") null else f[3]
            val og = if (f[4] == "Not routed") null else f[4]
            if (!v6mode) {
                val s = v4ToInt(f[0]) ?: continue
                val e = v4ToInt(f[1]) ?: continue
                st.add(s); en.add(e); asns.add(a); ccs.add(cc); orgs.add(og)
            } else {
                val s = v6ToBig(f[0]) ?: continue
                val e = v6ToBig(f[1]) ?: continue
                st6.add(s); en6.add(e); as6.add(a); cc6.add(cc); or6.add(og)
            }
        }
        if (!v6mode) {
            val n = st.size
            val idx = (0 until n).sortedBy { st[it] }
            val S = IntArray(n); val E = IntArray(n); val A = IntArray(n)
            val C = arrayOfNulls<String>(n); val O = arrayOfNulls<String>(n)
            for (i in 0 until n) { val j = idx[i]; S[i] = st[j]; E[i] = en[j]; A[i] = asns[j]; C[i] = ccs[j]; O[i] = orgs[j] }
            v4 = V4(S, E, A, C, O); rowsV4 = n
        } else {
            val n = st6.size
            val idx = (0 until n).sortedBy { st6[it] }
            val S = arrayOfNulls<BigInteger>(n); val E = arrayOfNulls<BigInteger>(n)
            val A = IntArray(n); val C = arrayOfNulls<String>(n); val O = arrayOfNulls<String>(n)
            for (i in 0 until n) { val j = idx[i]; S[i] = st6[j]; E[i] = en6[j]; A[i] = as6[j]; C[i] = cc6[j]; O[i] = or6[j] }
            v6 = V6(S.requireNoNulls(), E.requireNoNulls(), A, C, O); rowsV6 = n
        }
    }

    /** پارس CSV «DB-IP Country Lite» (start,end,cc) برای کشور جغرافیایی. */
    fun loadDbipCsv(input: InputStream) {
        val st = ArrayList<Int>(400000); val en = ArrayList<Int>(400000); val ccs = ArrayList<String?>(400000)
        val br = BufferedReader(input, 1 shl 20)
        while (true) {
            val line = br.readLine() ?: break
            if (line.isEmpty() || line.startsWith("#")) continue
            val f = line.split(',')
            if (f.size < 3) continue
            val s = v4ToInt(f[0]) ?: continue
            val e = v4ToInt(f[1]) ?: continue
            st.add(s); en.add(e); ccs.add(f[2].trim().ifEmpty { null })
        }
        val n = st.size
        val idx = (0 until n).sortedBy { st[it] }
        val S = IntArray(n); val E = IntArray(n); val C = arrayOfNulls<String>(n)
        for (i in 0 until n) { val j = idx[i]; S[i] = st[j]; E[i] = en[j]; C[i] = ccs[j] }
        geo = V4(S, E, IntArray(n), C, arrayOfNulls(n)); rowsGeo = n
    }

    private fun findV4(t: V4, ip: Int): Int {
        var lo = 0; var hi = t.starts.size - 1
        while (lo <= hi) {
            val mid = (lo + hi) ushr 1
            val s = t.starts[mid]
            if (ip < s) hi = mid - 1
            else if (ip > t.ends[mid]) lo = mid + 1
            else return mid
        }
        return -1
    }

    private fun findV6(t: V6, ip: BigInteger): Int {
        var lo = 0; var hi = t.starts.size - 1
        while (lo <= hi) {
            val mid = (lo + hi) ushr 1
            if (ip < t.starts[mid]) hi = mid - 1
            else if (ip > t.ends[mid]) lo = mid + 1
            else return mid
        }
        return -1
    }

    /** نتیجهٔ کامل برای یک IP: کشور BGP، کشور GeoIP، ASN، سازمان. */
    fun lookup(ip: String): Map<String, String?> {
        val out = LinkedHashMap<String, String?>()
        if (ip.contains(":")) {
            val b = v6ToBig(ip) ?: return out
            val t = v6 ?: return out
            val i = findV6(t, b)
            if (i >= 0) {
                out["cc_bgp"] = t.cc[i]
                val a = t.asn[i]; if (a > 0) out["asn"] = a.toString()
                out["org"] = t.org[i]
                out["prefix_v6"] = "—"
            }
        } else {
            val n = v4ToInt(ip) ?: return out
            v4?.let { t ->
                val i = findV4(t, n)
                if (i >= 0) {
                    out["cc_bgp"] = t.cc[i]
                    val a = t.asn[i]; if (a > 0) out["asn"] = a.toString()
                    out["org"] = t.org[i]
                    out["range"] = "%s-%s".format(ipFromInt(t.starts[i]), ipFromInt(t.ends[i]))
                }
            }
            geo?.let { g ->
                val i = findV4(g, n)
                if (i >= 0) out["cc_geo"] = g.cc[i]
            }
        }
        out["source"] = "ip2asn (BGP·Public Domain) + DB-IP Country Lite (CC BY 4.0) — آفلاین"
        return out
    }

    private fun ipFromInt(n: Int): String =
        "${(n ushr 24) and 255}.${(n ushr 16) and 255}.${(n ushr 8) and 255}.${n and 255}"

    /** خودآزمون واقعی روی چند IP شناخته‌شده — نتیجه به کاربر نشان داده می‌شود. */
    fun selfTest(): String {
        val cases = listOf(
            Triple("1.1.1.1", "13335", "US"),
            Triple("8.8.8.8", "15169", "US"),
            Triple("178.22.122.100", null, "IR"),
            Triple("217.218.155.155", null, "IR"),
            Triple("9.9.9.9", "19281", "US"),
        )
        var pass = 0
        val lines = ArrayList<String>(cases.size)
        for ((ip, wantAsn, wantCc) in cases) {
            val r = lookup(ip)
            val asn = r["asn"]; val cc = r["cc_bgp"] ?: r["cc_geo"]
            val okA = wantAsn == null || asn == wantAsn
            val okC = wantCc == null || cc == wantCc
            val ok = (asn != null) && okA && okC
            if (ok) pass++
            lines.add("%s → AS%s · %s · %s".format(ip, asn ?: "—", cc ?: "—", if (ok) "✅" else "❌"))
        }
        val head = "خودآزمون دیتابیس آفلاین: %d/%d".format(pass, cases.size)
        return "{\"pass\":$pass,\"total\":${cases.size},\"head\":\"$head\",\"lines\":[${lines.joinToString(",") { "\"" + it.replace("\"", "") + "\"" }}]}"
    }
}
