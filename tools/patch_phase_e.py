#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پچ فاز E روی cloudflare/worker.src.mjs — کالبدشکافی فیلترینگ + مهندسی نتِ بد."""
import re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "cloudflare" / "worker.src.mjs"
HELP = ROOT / "cloudflare" / "phase_e_helpers.js"
ROUTES = ROOT / "cloudflare" / "phase_e_routes.js"

src = SRC.read_text(encoding="utf-8")
helpers = HELP.read_text(encoding="utf-8")
routes = ROUTES.read_text(encoding="utf-8")

if "Phase E — کالبدشکافی فیلترینگ" in src:
    print("already patched"); sys.exit(0)

# ۱) توابع کمکی قبل از export default
anchor1 = "export default {"
assert anchor1 in src, "anchor1 missing"
src = src.replace(anchor1, helpers + "\n" + anchor1, 1)

# ۲) مسیرها قبل از بلوک PWA
anchor2 = '      /* --- 📲 PWA: مانیفست و سرویس‌ورکر --- */'
assert anchor2 in src, "anchor2 missing"
src = src.replace(anchor2, routes + "\n" + anchor2, 1)

# ۳) سرویس‌ورکر نسخهٔ ۳ (کش کهنه + صف آفلاین + گزارش وضعیت)
SW = r'''const C="pinghab-v3",A="pinghab-api-v1";
self.addEventListener("install",e=>{e.waitUntil(caches.open(C).then(c=>c.add("/app")).catch(()=>{}));self.skipWaiting()});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C&&k!==A).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
function idb(){return new Promise((res,rej)=>{var r=indexedDB.open("ph-q",1);r.onupgradeneeded=function(){if(!r.result.objectStoreNames.contains("q"))r.result.createObjectStore("q",{autoIncrement:true})};r.onsuccess=function(){res(r.result)};r.onerror=function(){rej(r.error)}})}
function add(body){return idb().then(db=>new Promise(res=>{var tx=db.transaction("q","readwrite");tx.objectStore("q").add({body:body,at:Date.now()});tx.oncomplete=function(){res(true)};tx.onerror=function(){res(false)}})).catch(()=>false)}
function del(key){return idb().then(db=>new Promise(res=>{var tx=db.transaction("q","readwrite");tx.objectStore("q").delete(key);tx.oncomplete=function(){res(true)};tx.onerror=function(){res(false)}})).catch(()=>false)}
function count(){return idb().then(db=>new Promise(res=>{var tx=db.transaction("q","readonly");var rq=tx.objectStore("q").count();rq.onsuccess=function(){res(rq.result||0)};rq.onerror=function(){res(0)}})).catch(()=>0)}
function drain(){return idb().then(db=>new Promise(res=>{var tx=db.transaction("q","readonly");var rq=tx.objectStore("q").getAll();var rk=tx.objectStore("q").getAllKeys();var o={items:[],keys:[]};rq.onsuccess=function(){o.items=rq.result||[]};rk.onsuccess=function(){o.keys=rk.result||[]};tx.oncomplete=function(){res(o)};tx.onerror=function(){res(o)}})).then(o=>{var i=0;function next(){if(i>=o.items.length)return Promise.resolve();var it=o.items[i],key=o.keys[i];i++;return fetch("/api/report",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(it.body||{})}).then(r=>{if(r.ok)return del(key);}).catch(()=>{}).then(next)}return next()}).catch(()=>{})}
self.addEventListener("sync",e=>{if(e.tag==="ph-flush")e.waitUntil(drain())});
self.addEventListener("message",e=>{var p=e.data||{};if(p.type==="ph-status"){e.waitUntil(Promise.all([caches.open(A).then(c=>c.keys()).then(ks=>Promise.all(ks.map(rq=>c.match(rq).then(m=>({path:new URL(rq.url).pathname+new URL(rq.url).search,at:(m&&m.headers.get("x-ph-at"))?parseInt(m.headers.get("x-ph-at"),10):null}))))),count()]).then(r=>{if(e.source)e.source.postMessage({type:"ph-status",items:r[0],queued:r[1]})}))}});
self.addEventListener("fetch",e=>{var req=e.request;var u=new URL(req.url);if(u.origin!==location.origin)return;
if(req.method==="POST"&&u.pathname==="/api/report"){e.respondWith(fetch(req.clone()).then(r=>{if(r.ok)return r;throw 0}).catch(()=>req.clone().json().catch(()=>({})).then(b=>add(b)).then(()=>{if(self.registration.sync){return self.registration.sync.register("ph-flush").catch(()=>{})}}).then(()=>new Response(JSON.stringify({ok:true,queued:true}),{headers:{"Content-Type":"application/json"}}))));return}
if(req.method!=="GET")return;
if(u.pathname.indexOf("/api/")===0){e.respondWith(caches.open(A).then(c=>fetch(req).then(r=>{if(r.ok){var hd=new Headers(r.headers);hd.set("x-ph-at",String(Date.now()));var cl=r.clone();return cl.arrayBuffer().then(buf=>c.put(req,new Response(buf,{status:200,headers:hd})).catch(()=>{})).then(()=>r)}return r}).catch(()=>c.match(req).then(m=>{if(!m)return new Response(JSON.stringify({ok:false,offline:true}),{headers:{"Content-Type":"application/json"}});var h2=new Headers(m.headers);h2.set("x-ph-stale","1");return m.arrayBuffer().then(buf=>new Response(buf,{status:200,headers:h2}))}))));return}
e.respondWith(fetch(req).then(r=>{var cl=r.clone();caches.open(C).then(c=>c.put(req,cl)).catch(()=>{});return r}).catch(()=>caches.match(req).then(m=>m||caches.match("/app"))))});
'''

pat = re.compile(r'      if \(p === "/sw\.js"\) \{.*?application/javascript; charset=utf-8", \.\.\.CORS \} \}\);\n      \}\n', re.S)
new_block = ('      if (p === "/sw.js") {\n        return new Response(`' + SW + '`, '
             '{ headers: { "Content-Type": "application/javascript; charset=utf-8", ...CORS } });\n      }\n')
src, n = pat.subn(lambda _m: new_block, src, count=1)
assert n == 1, "sw block not replaced"

# ۴) مستندات: افزودن مسیرهای تازه
doc_anchor = '    ["GET", "/api/ping · /api/load", "RTT + بار مصنوعی (آزمون بافر‌بلاست)"],\n'
assert doc_anchor in src, "docs anchor missing"
new_rows = doc_anchor + (
    '    ["GET", "/api/filter?host=…", "🕵️ کالبدشکافی فیلترینگ: چالهٔ DNS؟ IP مسدود؟ لایهٔ TLS؟ (شاهد خام + اطمینان)"],\n'
    '    ["GET", "/api/vantage?host=…&near=1", "📍 دسترسی از ۶ شهر ایران + ۳ گرهٔ همسایه (TCP/HTTPS)"],\n'
    '    ["GET", "/api/wave?host=…&packets=14&cc=IR", "🌊 آزمون موج: جیتر، افت، بافت‌نگار از پروب‌های ایران"],\n'
    '    ["GET", "/api/asn?ip=…", "ASN هر آی‌پی (Team Cymru، پشتیبان RIPEstat)"],\n'
    '    ["GET", "/api/ix?asn=44244", "IX های یک ASN (PeeringDB)"],\n'
    '    ["GET", "/api/ioda?cc=IR&hours=24", "🛑 قطعی‌ها از IODA (جورجیا تک)"],\n'
    '    ["GET", "/api/edns", "🧭 TCP/53 از ایران + سلامت مسیر DNS (DNS Flag Day 2020)"],\n'
    '    ["POST/GET", "/api/rtc?code=…", "🎙 سیگنالینگ دو-دستگاهی برای آزمون UDP (اتاق ۱۵ دقیقه‌ای)"],\n'
)
src = src.replace(doc_anchor, new_rows, 1)

SRC.write_text(src, encoding="utf-8")
print("patched ok:", len(src), "bytes")
