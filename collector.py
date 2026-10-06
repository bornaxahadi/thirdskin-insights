# Third Skin Insights – data collector.
# Runs inside the Composio remote workbench (has run_composio_tool + requests).
# Pulls Google Analytics 4 (property 557594788) + live site checks and writes data.json
# to the GitHub repo bornaxahadi/thirdskin-insights (served by GitHub Pages).
import json, re, time, base64, datetime, requests

P = "properties/557594788"
REPO = "bornaxahadi/thirdskin-insights"
SITE = "https://thirdskin.online/"


def _rows(d):
    dh = [h['name'] for h in d.get('dimensionHeaders', [])]
    mh = [h['name'] for h in d.get('metricHeaders', [])]
    out = []
    for r in d.get('rows', []) or []:
        rec = dict(zip(dh, [x.get('value') for x in r.get('dimensionValues', [])]))
        for k, v in zip(mh, [x.get('value') for x in r.get('metricValues', [])]):
            try:
                rec[k] = float(v) if '.' in str(v) else int(v)
            except Exception:
                rec[k] = v
        out.append(rec)
    return out


def report(dims, mets, start="28daysAgo", end="today", limit=50, order=None):
    args = {"property": P, "dateRanges": [{"startDate": start, "endDate": end}],
            "dimensions": [{"name": d} for d in dims], "metrics": [{"name": m} for m in mets], "limit": limit}
    if order:
        args["orderBys"] = [{"desc": True, "metric": {"metricName": order}}]
    for _ in range(2):
        r, e = run_composio_tool("GOOGLE_ANALYTICS_RUN_REPORT", args)
        if not e:
            return _rows(r.get("data", r))
        time.sleep(2)
    return []


def realtime(dims, mets=("activeUsers",), minutes=29):
    args = {"property": P, "metrics": [{"name": m} for m in mets], "dimensions": [{"name": d} for d in dims],
            "minuteRanges": [{"startMinutesAgo": minutes, "endMinutesAgo": 0}], "limit": 50}
    r, e = run_composio_tool("GOOGLE_ANALYTICS_RUN_REALTIME_REPORT", args)
    return [] if e else _rows(r.get("data", r))


def totals(start, end="today"):
    t = report([], ["activeUsers", "newUsers", "sessions", "screenPageViews", "engagementRate",
                    "averageSessionDuration", "eventCount", "engagedSessions"], start, end, limit=1)
    return t[0] if t else {}


def site_health():
    out = {"checks": []}
    for path in ["", "fa/", "ar/", "sitemap.xml", "robots.txt", "media-kit.pdf", "privacy/"]:
        url = SITE + path
        try:
            t0 = time.time(); r = requests.get(url, timeout=30); ms = int((time.time() - t0) * 1000)
            out["checks"].append({"path": "/" + path, "status": r.status_code, "ms": ms, "kb": round(len(r.content) / 1024)})
        except Exception as ex:
            out["checks"].append({"path": "/" + path, "status": 0, "ms": 0, "kb": 0, "err": str(ex)[:80]})
    home = out["checks"][0]
    out["up"] = all(c["status"] == 200 for c in out["checks"])
    out["homeMs"] = home["ms"]
    try:
        h = requests.get(SITE, timeout=30).text
        out["title"] = re.search(r"<title>([^<]*)", h).group(1)
        out["hasGA"] = "G-MZWRKFNXNN" in requests.get(SITE + "app.js", timeout=30).text
        out["altImgs"] = len(re.findall(r'<img[^>]+alt="[^"]+"', h))
        out["imgs"] = len(re.findall(r"<img", h))
    except Exception:
        pass
    return out


def social():
    try:
        js = requests.get(SITE + "app.js", timeout=30).text
        ig = int(float(re.search(r"ig:\{followers:([\d.e]+)", js).group(1)))
        fb = int(float(re.search(r"fb:\{followers:([\d.e]+)", js).group(1)))
    except Exception:
        ig, fb = 322000, 68000
    return {"ig": ig, "fb": fb, "total": ig + fb, "igGain30": 45800, "fbGain28": 14212,
            "igViews30": 23500000, "fbViews28": 11000000, "asOf": "4 Oct 2026"}


PERIODS = {"today": ("today", "today", "yesterday", "yesterday"),
           "d7": ("7daysAgo", "today", "14daysAgo", "8daysAgo"),
           "d30": ("30daysAgo", "today", "60daysAgo", "31daysAgo")}
TOT = ["activeUsers", "newUsers", "sessions", "screenPageViews", "engagementRate",
       "averageSessionDuration", "eventCount", "engagedSessions"]


def period_jobs(key, start, end, pstart, pend):
    return {
        "totals": (lambda: (report([], TOT, start, end, limit=1) or [{}])[0]),
        "prev": (lambda: (report([], TOT, pstart, pend, limit=1) or [{}])[0]),
        "countries": (lambda: report(["country", "countryId"], ["activeUsers", "sessions"], start, end, order="activeUsers", limit=30)),
        "regions": (lambda: report(["region", "country", "countryId"], ["activeUsers"], start, end, order="activeUsers", limit=20)),
        "cities": (lambda: report(["city", "countryId"], ["activeUsers"], start, end, order="activeUsers", limit=20)),
        "languages": (lambda: report(["language", "languageCode"], ["activeUsers"], start, end, order="activeUsers", limit=15)),
        "pages": (lambda: report(["pagePath"], ["screenPageViews", "activeUsers"], start, end, order="screenPageViews", limit=20)),
        "devices": (lambda: report(["deviceCategory"], ["activeUsers"], start, end, order="activeUsers")),
        "channels": (lambda: report(["sessionDefaultChannelGroup"], ["sessions"], start, end, order="sessions")),
        "sources": (lambda: report(["sessionSource"], ["sessions"], start, end, order="sessions", limit=12)),
        "events": (lambda: report(["eventName"], ["eventCount"], start, end, order="eventCount", limit=40)),
        "newret": (lambda: report(["newVsReturning"], ["activeUsers"], start, end)),
    }


def collect():
    from concurrent.futures import ThreadPoolExecutor
    now = datetime.datetime.now(datetime.timezone.utc)
    data = {"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "periods": {}}
    jobs = {}
    for k, (a, b, c, d) in PERIODS.items():
        for name, fn in period_jobs(k, a, b, c, d).items():
            jobs[(k, name)] = fn
    jobs[("x", "daily")] = lambda: sorted(report(["date"], ["activeUsers", "sessions", "screenPageViews"], limit=60, start="45daysAgo"), key=lambda r: r["date"])
    jobs[("x", "hours")] = lambda: report(["hour"], ["activeUsers"], "30daysAgo", "today", limit=24)
    jobs[("rt", "countries")] = lambda: realtime(["country", "countryId"])
    jobs[("rt", "cities")] = lambda: realtime(["city"])
    jobs[("rt", "devices")] = lambda: realtime(["deviceCategory"])
    jobs[("rt", "pages")] = lambda: realtime(["unifiedScreenName"], ("activeUsers", "screenPageViews"))
    jobs[("rt", "events")] = lambda: realtime(["eventName"], ("eventCount",))
    jobs[("x", "site")] = site_health
    jobs[("x", "social")] = social
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {key: ex.submit(fn) for key, fn in jobs.items()}
        res = {}
        for key, f in futs.items():
            try:
                res[key] = f.result(timeout=150)
            except Exception:
                res[key] = [] if key[1] not in ("totals", "prev", "site", "social") else {}
    for k in PERIODS:
        data["periods"][k] = {name: res[(k, name)] for name in period_jobs(k, *PERIODS[k]).keys()}
    rt = {n: res[("rt", n)] for n in ("countries", "cities", "devices", "pages", "events")}
    rt["active"] = sum(r.get("activeUsers", 0) for r in rt["countries"])
    data["realtime"] = rt
    data["daily"] = res[("x", "daily")]; data["hours"] = res[("x", "hours")]
    data["site"] = res[("x", "site")]; data["social"] = res[("x", "social")]
    # backwards-compatible keys
    data["t28"] = data["periods"]["d30"]["totals"]
    site = data["site"]
    data["setup"] = [
        {"name": "Website online", "state": "ok" if site.get("up") else "bad", "label": "All pages OK" if site.get("up") else "Problem"},
        {"name": "Google Analytics", "state": "ok" if site.get("hasGA") else "bad", "label": "Recording" if site.get("hasGA") else "Missing"},
        {"name": "Google Search Console", "state": "ok", "label": "Verified"},
        {"name": "Bing Webmaster Tools", "state": "ok", "label": "Verified"},
        {"name": "Microsoft Clarity", "state": "ok", "label": "Recording"},
        {"name": "IndexNow (Bing, Yandex)", "state": "ok", "label": "Active"},
        {"name": "Sitemap + image sitemap", "state": "ok", "label": "Submitted"},
        {"name": "Images with alt text", "state": "ok", "label": str(site.get("altImgs", "")) + " described"},
        {"name": "Google Business Profile", "state": "wait", "label": "Verify"},
        {"name": "Contact form (FormSubmit)", "state": "wait", "label": "Activate email"},
    ]
    return data


def publish(data):
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path = "data.json"
    cur, _ = proxy_execute("GET", f"/repos/{REPO}/contents/{path}", "github", query_params={"ref": "main"})
    payload = {"message": "Update insights data " + data["updated"],
               "content": base64.b64encode(body.encode()).decode(), "branch": "main"}
    if isinstance(cur, dict) and cur.get("sha"):
        payload["sha"] = cur["sha"]
    r, e = proxy_execute("PUT", f"/repos/{REPO}/contents/{path}", "github", body=payload)
    return e or "ok"


DATA = collect()
RESULT = publish(DATA)
print("published:", RESULT, "| active now:", DATA["realtime"]["active"], "| 30d users:", DATA["t28"].get("activeUsers"))
