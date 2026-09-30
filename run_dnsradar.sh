#!/usr/bin/env bash
# رادار DNS — اجراکنندهٔ آسان (لینوکس / مک / ترموکس اندروید)
# استفاده:  bash run_dnsradar.sh
set -u
cd "$(dirname "$0")"

# پیدا کردن پایتون (در ترموکس معمولاً python، در لینوکس python3)
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "❌ پایتون پیدا نشد."
  echo "   اندروید/ترموکس:  pkg update && pkg install python"
  echo "   لینوکس/دبیان :  sudo apt install python3"
  exit 1
fi

R() { printf '\033[0m'; }
G() { printf '\033[32m'; }
Y() { printf '\033[33m'; }
C() { printf '\033[36m'; }

banner() {
  clear 2>/dev/null || true
  C; echo "╔══════════════════════════════════════════════════════════╗"
  echo "║            📡  رادار DNS  —  اسکنر دی‌ان‌اس گیمینگ          ║"
  echo "╚══════════════════════════════════════════════════════════╝"; R
  echo "  پایتون: $(command -v "$PY")  |  پوشه: $(pwd)"
  echo "  ⚠️  DNS پینگ داخل بازی را کم نمی‌کند؛ ورود/تحریم/آپدیت/CDN را بهتر می‌کند."
  echo
}

ask_label() {
  printf "برچسب این اجرا (نام اپراتور/شهر، مثلاً «ایرانسل تهران»): "
  read -r LBL
  [ -z "$LBL" ] && LBL="پیش‌فرض"
  echo "$LBL"
}

menu() {
  banner
  cat <<'EOF'
   ۱) ⚡️ اسکن سریع (۷ سرور پرکاربرد)          ~۲۰ ثانیه
   ۲) 🎮 اسکن گیمینگ (ایرانی + جهانی)          ~۴۵ ثانیه
   ۳) 🇮🇷 فقط دی‌ان‌اس‌های ایرانی/رفع تحریم      ~۴۰ ثانیه
   ۴) 🌍 اسکن کامل (همهٔ ۴۸ سرور)              ~۶۰ ثانیه
   ۵) 🛡 خانواده (فیلتر محتوای بزرگسال)
   ۶) 📄 ساخت گزارش HTML از آخرین نتیجه
   ۷) 🎯 تست مسیر تا سرور بازی (آی‌پی دلخواه)
   ۸) 🤖 اجرای بات تلگرام
   ۹) 📖 راهنمای پینگ و تنظیم DNS روی گوشی
  ۱۰) 📡 داشبورد زنده (پینگ لحظه‌ای بر اساس منطقه)
   ۰) 🚪 خروج
EOF
  printf "\nانتخاب: "
  read -r CH
  case "$CH" in
    1) S="cloudflare,google,quad9,shecan,radar,electro,adguard,dnssb"; A=6; N="$(ask_label)"; GO "$S" "$A" "$N" ;;
    2) S="radar,electro,shecan,begzar,vanilla,zeus,shelter,cloudflare,google,quad9,dnssb,adguard"; A=8; N="$(ask_label)+گیم"; GO "$S" "$A" "$N" ;;
    3) S="shecan,radar,electro,begzar,403online,vanilla,zeus,shelter,tci,hostiran,serverir,shatel,greenteam,parsonline"; A=8; N="$(ask_label)+ایران"; GO "$S" "$A" "$N" ;;
    4) R; "$PY" dnsscan.py --preset all --attempts 8 --name "$(ask_label)" ;;
    5) R; "$PY" dnsscan.py --preset family --attempts 8 --name "خانواده" ;;
    6) R; LAST=$(ls -1t reports/*/report.html reports/report.html 2>/dev/null | head -1)
       if [ -z "${LAST:-}" ]; then echo "گزارشی پیدا نشد."; else
         echo "📄 $LAST"; command -v termux-open >/dev/null 2>&1 && termux-open "$LAST" || \
         (command -v xdg-open >/dev/null 2>&1 && xdg-open "$LAST" || echo "فایل را با مرورگر باز کن.")
       fi ;;
    7) R; printf "آی‌پی سرور بازی (مثلاً از اپ PCAPdroid/NetGuard پیدا کن): "; read -r GIP
       printf "برچسب: "; read -r GLB; [ -z "$GLB" ] && GLB="سرور بازی"
       "$PY" dnsscan.py --preset quick --attempts 4 --no-dot --no-doh --game-ips "$GIP:$GLB" --name "مسیر بازی" ;;
    8) R; echo "برای اجرای بات اول توکن بگیر (@BotFather) و بعد:"
       echo "  export TELEGRAM_BOT_TOKEN=\"توکن\"; $PY bot.py"; echo
       if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then "$PY" bot.py; else
         printf "توکن را همین حالا وارد می‌کنی؟ (y/n): "; read -r YN
         if [ "$YN" = "y" ]; then printf "توکن: "; read -r TK; TELEGRAM_BOT_TOKEN="$TK" "$PY" bot.py; fi
       fi ;;
    9) R; "$PY" - <<'PYEOF'
print(open('راهنمای-اندروید.md', encoding='utf-8').read()[:4000] if __import__('os').path.exists('راهنمای-اندروید.md')
      else "فایل راهنما پیدا نشد.")
PYEOF
       ;;
    10) R; echo "📡 داشبورد زنده روی http://127.0.0.1:8777 بالا می‌آید…"
        ( "$PY" dnsserve.py --port 8777 --cycle 3 >/tmp/dnsradar-live.log 2>&1 & )
        sleep 3
        if command -v termux-open-url >/dev/null 2>&1; then termux-open-url "http://127.0.0.1:8777"
        elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://127.0.0.1:8777"
        else echo "در مرورگر باز کن: http://127.0.0.1:8777"; fi
        echo "(توقف: pkill -f dnsserve.py)";;
    0) exit 0 ;;
    *) echo "انتخاب نامعتبر.";;
  esac
  printf "\n%sبرای بازگشت به منو Enter بزن..." "$Y"; read -r _; menu
}

GO() {
  R
  echo; G; echo "▶ شروع اسکن..."; R
  "$PY" dnsscan.py --servers "$1" --attempts "$2" --name "$3"
  LAST=$(ls -1t reports/report.html 2>/dev/null | head -1)
  if [ -n "${LAST:-}" ]; then
    echo; G; echo "✅ گزارش ساخته شد: $LAST"; R
    if command -v termux-open >/dev/null 2>&1; then
      printf "باز کردن در مرورگر؟ (y/n): "; read -r YN; [ "$YN" = "y" ] && termux-open "$LAST"
    fi
  fi
}

menu
