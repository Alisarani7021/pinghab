      /* --- 🕵️ فاز E: کالبدشکافی فیلترینگ --- */
      if (p === "/api/filter") {
        const host = (url.searchParams.get("host") || "").trim().toLowerCase().slice(0, 100);
        if (!/^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$/.test(host)) return json({ ok: false, error: "دامنهٔ نامعتبر" }, 400);
        return json(await filterProbe(env, host));
      }
      if (p === "/api/vantage") {
        const host = (url.searchParams.get("host") || "").trim().toLowerCase().slice(0, 100);
        if (!/^[a-z0-9][a-z0-9.\-]*\.[a-z0-9]{2,}$|^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return json({ ok: false, error: "هدف نامعتبر" }, 400);
        return json(await vantageProbe(env, host, url.searchParams.get("near") === "1"));
      }
      if (p === "/api/wave") {
        const host = (url.searchParams.get("host") || "1.1.1.1").trim().slice(0, 100);
        const packets = parseInt(url.searchParams.get("packets") || "14", 10) || 14;
        const cc = (url.searchParams.get("cc") || "IR").slice(0, 2);
        return json(await waveProbe(env, host, packets, cc));
      }
      if (p === "/api/asn") {
        const ip = (url.searchParams.get("ip") || "").trim().slice(0, 45);
        if (!/^[0-9a-fA-F.:]+$/.test(ip)) return json({ ok: false, error: "آی‌پی نامعتبر" }, 400);
        return json({ ok: true, ...(await asnInfo(env, ip)) });
      }
      if (p === "/api/ix") {
        const asn = parseInt(url.searchParams.get("asn") || "0", 10);
        if (!asn) return json({ ok: false, error: "asn لازم است" }, 400);
        return json(await ixInfo(env, asn));
      }
      if (p === "/api/ioda") {
        const cc = (url.searchParams.get("cc") || "IR").slice(0, 2).toUpperCase();
        const hours = parseInt(url.searchParams.get("hours") || "24", 10) || 24;
        return json(await iodaGet(env, cc, hours));
      }
      if (p === "/api/edns") return json(await ednsProbe(env));
      if (p === "/api/rtc") return rtcHandle(env, request, url);
