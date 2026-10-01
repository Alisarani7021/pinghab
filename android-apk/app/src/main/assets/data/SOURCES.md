# داده‌های واقعی همراه اپ (assets/data) — منبع و مجوز هر فایل

| فایل | چیست | منبع | مجوز |
|---|---|---|---|
| `ip2asn-v4.tsv` | ۴۵۰هزار بازهٔ واقعی IPv4: ASN + کشور + نام سازمان (از جدول مسیرهای BGP) | iptoasn.com | Public Domain |
| `ip2asn-v6.tsv` | همان برای IPv6 (بازه‌های اعلام‌شدهٔ v6) | iptoasn.com | Public Domain |
| `dbip-country.csv` | بازه‌های IPv4 با کد کشور جغرافیایی | DB-IP Lite | CC BY 4.0 |
| `resolvers-real.txt` | ۱۰٬۸۹۳ رزولور عمومی واقعی (تست‌شده) | github.com/trickest/resolvers | MIT |
| `subdomains-2m.txt` | ۲٬۱۷۱٬۶۸۷ نام زیردامنهٔ رایج (پویش DNS) | SecLists (dns-Jhaddix) | MIT |
| `subdomains-top110k.txt` | ۱۱۰٬۰۰۰ نام پرتکرار (پویش سریع) | SecLists (subdomains-top1million-110000) | MIT |
| `fonts/Vazirmatn-*.woff2` | فونت فارسی برای کار آفلاین | Vazirmatn (rastikerdar) | OFL 1.1 |

قاعده: هیچ‌کدام از این فایل‌ها جای عددِ سنجیده‌شده روی خط کاربر را نمی‌گیرد؛ برچسب‌ها از دادهٔ واقعی
می‌آیند و «کاندید، نه توصیه» سرجایش است. اپ هیچ داده‌ای از کاربر ذخیره یا ارسال نمی‌کند.


بسته‌بندی: این فایل‌ها در مخزن به‌صورت gzip هستند و Gradle هنگام ساخت APK آن‌ها را باز می‌کند؛
داخل APK با deflate فشرده می‌شوند (نسبت به حالت noCompress، حجم دانلود ~۴ برابر سبک‌تر می‌شود).
