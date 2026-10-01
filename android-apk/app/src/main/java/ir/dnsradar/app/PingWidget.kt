package ir.dnsradar.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import android.widget.RemoteViews
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * ویجت صفحهٔ خانه — «آخرین وضعیت خط» بدون باز کردن اپ.
 *
 * دو کار می‌کند:
 *  ۱) مقدار ذخیره‌شده را نشان می‌دهد (اپ هنگام هر سنجش، از طریق پل JS می‌نویسد:
 *     ms / نمرهٔ آمادگی / وضعیت / زیرنویس مثل «تهران · ایرانسل»).
 *  ۲) دکمهٔ تازه‌سازی خودش یک RTT سبک به لبهٔ پینگ‌هاب می‌زند و عدد را به‌روز می‌کند
 *     (بدون باز کردن اپ، با محدودیت زمانی و بدون هیچ دادهٔ شناسایی‌کننده).
 */
class PingWidget : AppWidgetProvider() {

    companion object {
        const val ACTION_REFRESH = "ir.dnsradar.app.WIDGET_REFRESH"
        const val PREFS = "ph_widget"
        const val SITE = "https://pinghab.catclient-59gk2mui.workers.dev"
        private const val TAG = "PingWidget"

        /** همهٔ نمونه‌های ویجت روی صفحه را بازسازی می‌کند (اپ هم همین را صدا می‌زند). */
        fun updateAll(context: Context) {
            try {
                val mgr = AppWidgetManager.getInstance(context)
                val ids = mgr.getAppWidgetIds(ComponentName(context, PingWidget::class.java))
                for (id in ids) render(context, mgr, id)
            } catch (t: Throwable) {
                Log.w(TAG, "updateAll failed: " + t.message)
            }
        }

        private fun render(context: Context, mgr: AppWidgetManager, id: Int) {
            val v = RemoteViews(context.packageName, R.layout.widget_ping)
            val sp = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val ms = sp.getInt("ms", -1)
            val score = sp.getInt("score", -1)
            val status = sp.getString("status", "برای سنجش، 🔄 را بزن") ?: ""
            val sub = sp.getString("sub", "") ?: ""
            val at = sp.getLong("at", 0L)

            v.setTextViewText(R.id.w_value, if (ms > 0) ms.toString() else "—")
            v.setTextViewText(R.id.w_unit, if (ms > 0) "ms" else "")
            v.setTextViewText(R.id.w_status, if (score >= 0) "$status · نمره $score" else status)
            v.setTextViewText(R.id.w_sub, if (sub.isEmpty()) "پینگ‌هاب" else sub)
            v.setTextViewText(
                R.id.w_at,
                if (at > 0) "به‌روزرسانی: " + SimpleDateFormat("HH:mm", Locale.US).format(Date(at)) else ""
            )
            v.setOnClickPendingIntent(R.id.w_refresh, refreshIntent(context))
            v.setOnClickPendingIntent(R.id.w_root, openIntent(context))
            mgr.updateAppWidget(id, v)
        }

        private fun refreshIntent(context: Context): PendingIntent {
            val i = Intent(context, PingWidget::class.java).setAction(ACTION_REFRESH)
            return PendingIntent.getBroadcast(context, 71, i, piFlags())
        }

        private fun openIntent(context: Context): PendingIntent {
            val i = Intent(context, MainActivity::class.java)
            i.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            return PendingIntent.getActivity(context, 72, i, piFlags())
        }

        private fun piFlags(): Int {
            var f = PendingIntent.FLAG_UPDATE_CURRENT
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) f = f or PendingIntent.FLAG_IMMUTABLE
            return f
        }
    }

    override fun onUpdate(context: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) render(context, mgr, id)
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action != ACTION_REFRESH) return
        val pending = goAsync()
        Thread {
            try {
                var measured = -1
                for (attempt in 0 until 2) {
                    val t0 = System.currentTimeMillis()
                    try {
                        val conn = URL("$SITE/api/ping?w=" + System.nanoTime()).openConnection() as HttpURLConnection
                        conn.connectTimeout = 8000
                        conn.readTimeout = 8000
                        conn.requestMethod = "GET"
                        conn.setRequestProperty("User-Agent", "PinghabWidget/1.0")
                        conn.inputStream.use { it.readBytes() }
                        measured = (System.currentTimeMillis() - t0).toInt()
                        conn.disconnect()
                        if (measured > 0) break
                    } catch (t: Throwable) {
                        measured = -1
                    }
                }
                val sp = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                val e = sp.edit()
                if (measured > 0) {
                    e.putInt("ms", measured)
                    e.putString("status", "اتصال به لبه برقرار")
                } else {
                    e.putString("status", "خط پاسخ نداد")
                }
                e.putLong("at", System.currentTimeMillis())
                e.apply()
            } catch (t: Throwable) {
                Log.w(TAG, "refresh failed: " + t.message)
            } finally {
                updateAll(context)
                pending.finish()
            }
        }.start()
    }
}
