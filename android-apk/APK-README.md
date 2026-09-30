# 📦 ساخت فایل APK «رادار DNS»

این پوشه یک پروژهٔ اندروید آماده است (Kotlin + WebView) که **نسخهٔ وب رادار** (`../web/dns-radar.html`) را داخل یک اپ نصب‌شدنی می‌گذارد.
اپ سبک است (زیر ۱ مگابایت)، به اینترنت اجازه می‌دهد و هیچ دسترسی دیگری نمی‌خواهد (نه مخاطبین، نه موقعیت، نه حافظه).

> ⚠️ من در محیط سندباکس **Android SDK نداشتم**، پس فایل APK را همین‌جا کامپایل و تست نکردم؛
> اما ساختار پروژه استاندارد است. اگر در ساخت خطایی دیدی، متن خطا را برایم بفرست تا درستش کنم.

## مشخصات فنی
- `applicationId`: `ir.dnsradar.app` · `minSdk 21` (اندروید ۵ به بالا) · `targetSdk 34`
- صفحهٔ اپ از منبع امن `https://appassets.androidplatform.net` سرو می‌شود تا درخواست‌های DoH بدون مشکل CORS کار کنند
- فایل وب **کپی نمی‌شود**؛ از خود پوشهٔ `../web` در `assets` قرار می‌گیرد (`sourceSets` در `app/build.gradle.kts`)

## روش ۱ — گیت‌هاب (رایگان، بدون نصب چیزی) ⭐ پیشنهادی
1. در [github.com](https://github.com) یک ریپازیتوری جدید بساز.
2. کل پوشهٔ `dnsradar` را آپلود کن (فایل `.github/workflows/build-apk.yml` هم داخلش هست).
3. به تب **Actions** برو → workflow به نام **Build APK** → دکمهٔ **Run workflow**.
4. بعد از ۲–۴ دقیقه، در همان اجرا پایین صفحه بخش **Artifacts** → دانلود `dnsradar-apk`.
5. فایل `app-debug.apk` را روی گوشی نصب کن (اجازهٔ «نصب از منابع ناشناس» را بده).

## روش ۲ — Android Studio (کامل‌ترین)
1. Android Studio (نسخهٔ ۲۰۲۳+) را نصب کن؛ JDK 17 لازم است.
2. `File › Open` → پوشهٔ `android-apk` را باز کن و بگذار Gradle Sync شود.
3. `Build › Build Bundle(s)/APK(s) › Build APK(s)` → فایل در `app/build/outputs/apk/debug/app-debug.apk`.

## روش ۳ — خط فرمان (اگر Android SDK داری)
```bash
 cd android-apk
 gradle assembleDebug        # یا ./gradlew assembleDebug اگر wrapper داشتی
```
خروجی: `app/build/outputs/apk/debug/app-debug.apk`

## انتشار نسخهٔ «امضاشده» برای پخش عمومی
`debug` برای خودت و دوستان کافی است. برای پخش عمومی حتماً `release` با کلید امضا بساز:
```bash
keytool -genkey -v -keystore dnsradar.jks -keyalg RSA -keysize 2048 -validity 10000 -alias dnsradar
```
و در `app/build.gradle.kts` یک `signingConfigs` اضافه کن. (اگر خواستی، برایت اضافه می‌کنم.)

## نکته‌ها
- اپ فقط تست DoH را انجام می‌دهد (محدودیت مرورگر/WebView). برای تست کامل UDP/53، DoT، جیتر و افت بسته
  همان `dnsscan.py` روی ترموکس یا کامپیوتر را اجرا کن؛ نتیجهٔ کامل‌تری می‌دهد.
- آیکون اپ از فایل `icon-src.png` ساخته شده و در `res/mipmap-*` در همهٔ تراکم‌ها موجود است.
- اگر بعد از نصب، اپ سفید ماند: در `MainActivity.kt` خط `loadUrl` را به
  `"https://appassets.androidplatform.net/assets/dns-radar.html"` چک کن (فایل باید در پوشهٔ `web` باشد).
