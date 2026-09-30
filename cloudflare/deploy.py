#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ساخت و انتشار «پینگ‌هاب» روی Cloudflare Workers
=========================================================================
  python3 deploy.py build     # فقط ساخت فایل نهایی (dist/worker.mjs)
  python3 deploy.py deploy    # ساخت + آپلود روی Cloudflare + فعال‌سازی
  python3 deploy.py setup     # تنظیم وب‌هوک و دستورهای بات تلگرام
  python3 deploy.py test      # تست زندهٔ همهٔ مسیرهای Worker
  python3 deploy.py all       # همهٔ مراحل با هم
توکن‌ها از فایل ../.env خوانده می‌شوند (هرگز در گیت کامیت نمی‌شود).
"""
from __future__ import annotations
import json, os, sys, time, urllib.request, urllib.error, uuid
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = HERE / "dist"
SITE = "https://pinghab.catclient-59gk2mui.workers.dev"
SCRIPT_NAME = "pinghab"
KV_TITLE = "DNSRADAR_KV"


def load_env() -> dict:
    env = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in ("CLOUDFLARE_API_TOKEN", "TELEGRAM_BOT_TOKEN", "CF_ACCOUNT_ID"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def api(url, token, method="GET", body=None, headers=None, raw=False, timeout=60):
    h = {"Authorization": f"Bearer {token}", "User-Agent": "PingHab/1.0 (+https://github.com/Alisarani7021/pinghab)"}
    h.update(headers or {})
    data = body if isinstance(body, (bytes, str)) else (json.dumps(body).encode() if body is not None else None)
    if data is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read().decode("utf-8", "ignore")
            return r.status, (b if raw else (json.loads(b) if b else {}))
    except urllib.error.HTTPError as e:
        b = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(b)
        except Exception:
            return e.code, {"raw": b[:600]}
    except Exception as e:
        return None, {"error": f"{type(e).__name__}: {e}"}


# --------------------------------------------------------------------- build

def build() -> Path:
    app = (HERE / "app.html").read_text(encoding="utf-8")
    src = (HERE / "worker.src.mjs").read_text(encoding="utf-8")
    out = src.replace("__APP_HTML__", json.dumps(app, ensure_ascii=False))

    # --- کاتالوگ DNS جهانی (WorldScan) در زمان build تزریق می‌شود ---
    cat_path = ROOT / "data" / "dns_world" / "catalog.json"
    cur_path = ROOT / "data" / "dns_world" / "curated.json"
    if cat_path.exists() and cur_path.exists():
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        cur = json.loads(cur_path.read_text(encoding="utf-8"))
        # فقط آنچه در Worker لازم است (حجم را کم نگه می‌داریم)
        small = {
            "generated_at": cat.get("generated_at"),
            "source": cat.get("source_url"),
            "totals": cat.get("totals"),
            "countries": {k: {"name_fa": v["name_fa"], "count": v["count"], "v4": v["v4"],
                              "v6": v["v6"], "top": v["top"][:25]}
                          for k, v in cat.get("countries", {}).items()},
        }
        groups = []
        for g in cur.get("groups", []):
            cc = "IR" if g["id"] == "iran" else "GL"
            groups.append({"id": g["id"], "cc": cc, "entries": [
                {"name": e["name"], "v4": e.get("v4") or [], "v6": e.get("v6") or [],
                 "doh": e.get("doh"), "dot": e.get("dot"), "note": e.get("note", "")}
                for e in g.get("entries", [])]})
        blob = {"generated_at": cur.get("generated_at"), "source": cat.get("source_url"),
                "totals": cat.get("totals"), "curated_counts": cur.get("counts"),
                "countries": small["countries"], "curated_groups": groups}
        out = out.replace("__WORLD_CATALOG__", json.dumps(blob, ensure_ascii=False, separators=(",", ":")))
        print(f"   📚 کاتالوگ جهانی تزریق شد: {blob['totals']['servers']:,} سرور / "
              f"{blob['totals']['countries']} کشور / {len(groups)} گروه منتخب")
    else:
        out = out.replace("__WORLD_CATALOG__", '{"countries":{},"curated_groups":[]}')
    DIST.mkdir(exist_ok=True)
    target = DIST / "worker.mjs"
    target.write_text(out, encoding="utf-8")
    print(f"✅ ساخته شد: {target.relative_to(ROOT)}  ({len(out)/1024:.1f} KB · app {len(app)/1024:.1f} KB)")
    return target


# --------------------------------------------------------------------- deploy

def multipart(fields: dict, files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    """fields: name->str ; files: (name, filename, ctype, data)"""
    boundary = "----pinghab" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode() + b"\r\n"
    for name, filename, ctype, data in files:
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        out += f"Content-Type: {ctype}\r\n\r\n".encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), boundary


def deploy(env: dict) -> bool:
    token, acc = env["CLOUDFLARE_API_TOKEN"], env["CF_ACCOUNT_ID"]
    tg_token = env["TELEGRAM_BOT_TOKEN"]
    worker = build()

    # فضای KV
    st, j = api(f"https://api.cloudflare.com/client/v4/accounts/{acc}/storage/kv/namespaces?per_page=50", token)
    ns = next((n for n in (j.get("result") or []) if n.get("title") == KV_TITLE), None)
    if not ns:
        st, j = api(f"https://api.cloudflare.com/client/v4/accounts/{acc}/storage/kv/namespaces", token,
                    "POST", {"title": KV_TITLE})
        ns = j.get("result")
    if not ns:
        print("❌ ساخت فضای KV ناموفق:", str(j)[:300]); return False
    print(f"🗄 KV: {ns['title']} = {ns['id']}")

    webhook_secret = env.get("TG_WEBHOOK_SECRET") or (uuid.uuid4().hex + uuid.uuid4().hex[:16])
    admin_key = env.get("ADMIN_KEY") or uuid.uuid4().hex
    print("🔑 کلید وب‌هوک:", "بازاستفاده از .env" if env.get("TG_WEBHOOK_SECRET") else "تولید جدید",
          "| کلید مدیریت:", "بازاستفاده از .env" if env.get("ADMIN_KEY") else "تولید جدید")
    compat = (date.today() - timedelta(days=5)).isoformat()

    metadata = {
        "main_module": "worker.mjs",
        "compatibility_date": compat,
        "bindings": [
            {"type": "kv_namespace", "name": "DNSRADAR_KV", "namespace_id": ns["id"]},
            {"type": "secret_text", "name": "TG_TOKEN", "text": tg_token},
            {"type": "secret_text", "name": "TG_SECRET", "text": webhook_secret},
            {"type": "secret_text", "name": "ADMIN_KEY", "text": admin_key},
        ],
        "observability": {"enabled": True},
    }
    body, boundary = multipart(
        {"metadata": json.dumps(metadata, ensure_ascii=False)},
        [("worker.mjs", "worker.mjs", "application/javascript+module", worker.read_bytes())],
    )
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/workers/scripts/{SCRIPT_NAME}"
    hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    ok = False
    for method in ("PUT", "POST"):
        st, j = api(url, token, method, body, hdrs, timeout=120)
        print(f"   {method} → {st}  success={j.get('success')}  {str(j.get('errors') or '')[:200]}")
        if j.get("success"):
            ok = True; break
    if not ok:
        return False

    # فعال‌سازی workers.dev
    st, j = api(f"{url}/subdomain", token, "POST", {"enabled": True, "previews_enabled": True})
    print(f"🌐 فعال‌سازی workers.dev → {st} success={j.get('success')} {str(j.get('errors') or '')[:160]}")

    # ذخیرهٔ کلیدها در .env برای استفادهٔ بعدی
    txt = (ROOT / ".env").read_text(encoding="utf-8")
    for k, v in (("CF_KV_ID", ns["id"]), ("TG_WEBHOOK_SECRET", webhook_secret),
                 ("ADMIN_KEY", admin_key), ("SITE_URL", SITE), ("WORKER_NAME", SCRIPT_NAME)):
        if f"{k}=" not in txt:
            txt += f"{k}={v}\n"
    (ROOT / ".env").write_text(txt, encoding="utf-8")
    print("💾 کلیدهای جدید در .env ذخیره شد")
    print(f"🚀 آدرس سایت: {SITE}")
    return True


# --------------------------------------------------------------------- setup

def tg_call(tg_token: str, method: str, payload: dict):
    return api(f"https://api.telegram.org/bot{tg_token}/{method}", "x", "POST", payload,
               headers={"Authorization": "", "User-Agent": "PingHab/1.0"}, timeout=30)


def setup(env: dict):
    tg_token = env["TELEGRAM_BOT_TOKEN"]
    st, j = api(f"{SITE}/tg/setup?key={env.get('ADMIN_KEY','')}", "x", headers={"Authorization": "", "User-Agent": "PingHab/1.0"}, timeout=60)
    print("تنظیم وب‌هوک:", st, json.dumps(j, ensure_ascii=False)[:400] if j else "")
    st, info = api(f"https://api.telegram.org/bot{tg_token}/getWebhookInfo", "x",
                   headers={"Authorization": "", "User-Agent": "PingHab/1.0"})
    print("وضعیت وب‌هوک:", json.dumps((info or {}).get("result", {}), ensure_ascii=False)[:400])
    st, cmds = api(f"https://api.telegram.org/bot{tg_token}/getMyCommands", "x", headers={"Authorization": "", "User-Agent": "PingHab/1.0"})
    print("دستورها:", json.dumps((cmds or {}).get("result", []), ensure_ascii=False)[:300])


# --------------------------------------------------------------------- test

def test(env: dict):
    print("\n" + "=" * 74)
    print("تست زندهٔ سرویس")
    print("=" * 74)
    results = []

    def check(label, url, expect=200, headers=None, method="GET", body=None):
        st, raw = api(url, "x", method, body, headers or {"Authorization": "", "User-Agent": "PingHab/1.0"}, raw=True, timeout=60)
        ok = (st == expect)
        snippet = ""
        try:
            j = json.loads(raw)
            snippet = json.dumps(j, ensure_ascii=False)[:160]
        except Exception:
            snippet = str(raw)[:140].replace("\n", " ")
        results.append((label, ok, f"{st}"))
        print(f"  {'✅' if ok else '❌'} {label:34s} {str(st):>5s}  {snippet}")
        return raw

    check("صفحهٔ اصلی", f"{SITE}/")
    check("صفحهٔ مینیاپ", f"{SITE}/app")
    check("healthz", f"{SITE}/healthz")
    check("/api/me (شناسایی خط)", f"{SITE}/api/me")
    check("/api/edge (سلامت DNS)", f"{SITE}/api/edge")
    check("وب‌هوک بدون کلید (باید ۴۰۳)", f"{SITE}/tg/webhook", expect=403, method="POST", body={})
    body = json.dumps({"message": {"message_id": 1, "from": {"id": 999999999, "first_name": "تست"},
                                   "chat": {"id": 999999999, "type": "private"}, "text": "/start"}}).encode()
    check("وب‌هوک با کلید (باید ۲۰۰)", f"{SITE}/tg/webhook", expect=200, method="POST", body=body,
          headers={"Authorization": "", "Content-Type": "application/json",
                   "X-Telegram-Bot-Api-Secret-Token": env.get("TG_WEBHOOK_SECRET", "")})
    # ذخیره و لینک اشتراک
    payload = json.dumps({"results": [{"id": "cloudflare", "name": "کلودفلر", "dns": "1.1.1.1", "med": 42.3,
                                       "jit": 2.1, "loss": 0.0, "quality": 88},
                                      {"id": "google", "name": "گوگل", "dns": "8.8.8.8", "med": 61.0,
                                       "jit": 5.4, "loss": 0.1, "quality": 72}],
                          "me": {"asOrganization": "Iran Cell", "colo": "DXB"}, "regions": [{"region": "ترکیه", "flag": "🇹🇷", "ms": 78}]}).encode()
    raw = api(f"{SITE}/api/save", "x", "POST", payload,
              {"Authorization": "", "User-Agent": "PingHab/1.0", "Content-Type": "application/json"}, raw=True, timeout=60)
    sid = None
    try:
        j = json.loads(raw[1]); sid = j.get("id")
        print(f"  {'✅' if j.get('ok') else '❌'} {'/api/save':34s} {str(raw[0]):>5s}  id={sid}")
    except Exception as e:
        print("  ❌ save:", raw)
    if sid:
        check("صفحهٔ اشتراک نتیجه", f"{SITE}/r/{sid}")

    good = sum(1 for _, ok, _ in results if ok)
    print(f"\nنتیجه: {good}/{len(results)} بررسی موفق")
    return good == len(results)


if __name__ == "__main__":
    env = load_env()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "build":
        build()
    elif cmd == "deploy":
        deploy(env)
    elif cmd == "setup":
        setup(env)
    elif cmd == "test":
        test(env)
    elif cmd == "all":
        ok = deploy(env)
        if ok:
            time.sleep(6)
            setup(load_env())
            test(load_env())
    else:
        print(__doc__)
