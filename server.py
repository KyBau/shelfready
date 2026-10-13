#!/usr/bin/env python3
"""ShelfReady MCP server: lets AI agents shop any Shopify store through its PUBLIC catalog.
Wraps /products.json, /products/<handle>.js, /policies/* and /cart/<variant>:<qty> permalinks.
The human completes checkout on the merchant's own site; this server never touches payment.
Configured by store domain (SHELFREADY_STORE env or the per-call 'store' arg).
Transports: stdio (default) and stateless Streamable HTTP (`--http`, POST /mcp). Zero dependencies (Python 3.10+)."""
import json, os, re, sys, time, html, urllib.request, urllib.error, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
VERSION = "0.2.0"
SUPPORTED = ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"]
UA = "ShelfReady/0.1 (+agent catalog connector; read-only)"
RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
DEFAULT_STORE = os.environ.get("SHELFREADY_STORE", "")
# Merchant (single-store) mode is the default whenever SHELFREADY_STORE is set; the multi-store demo must opt in.
ALLOW_ANY = os.environ.get("SHELFREADY_ALLOW_ANY_STORE", "0" if DEFAULT_STORE else "1") == "1"
LOCKED = bool(DEFAULT_STORE) and not ALLOW_ANY
STORE_NAME = os.environ.get("SHELFREADY_STORE_NAME") or (DEFAULT_STORE.split(".")[0].replace("-", " ").title() if DEFAULT_STORE else "")
COLLECTIONS = [c.strip() for c in os.environ.get("SHELFREADY_COLLECTIONS", "").split(",") if re.fullmatch(r"[a-z0-9-]+", c.strip())]
REF = re.sub(r"[^A-Za-z0-9_-]", "", os.environ.get("SHELFREADY_REF", "shelfready"))
_STORE = {"type": "string", "description": "Store domain, e.g. 'allbirds.com'. Optional when the server is configured for one store."}
TOOLS = [
 {"name": "search_products", "title": "Search the store's products",
  "description": "Search the store's public catalog. Matches the query against title, product type, vendor and tags. Optional filters are max_price, min_price, product_type and in_stock_only. Returns handles, prices, availability and URLs. Read-only.",
  "inputSchema": {"type": "object", "properties": {"store": _STORE, "query": {"type": "string"}, "max_price": {"type": "number"}, "min_price": {"type": "number"},
     "product_type": {"type": "string"}, "in_stock_only": {"type": "boolean", "default": True}, "limit": {"type": "integer", "default": 10, "maximum": 25}},
     "required": ["query"], "additionalProperties": False},
  "annotations": {"title": "Search the store's products", **RO}},
 {"name": "get_product", "title": "Get product details",
  "description": "Get one product by handle, with every variant's id, options, price, compare-at price and availability. Read-only.",
  "inputSchema": {"type": "object", "properties": {"store": _STORE, "handle": {"type": "string"}}, "required": ["handle"], "additionalProperties": False},
  "annotations": {"title": "Get product details", **RO}},
 {"name": "build_cart_link", "title": "Build a checkout link for the shopper",
  "description": "Turn variant ids and quantities into a Shopify cart permalink. The human opens the link and completes checkout on the merchant's site. This tool does NOT place an order, take payment or reserve stock. It checks that each variant exists and is available.",
  "inputSchema": {"type": "object", "properties": {"store": _STORE, "items": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object",
     "properties": {"variant_id": {"type": "integer"}, "quantity": {"type": "integer", "minimum": 1, "maximum": 20, "default": 1}}, "required": ["variant_id"], "additionalProperties": False}}},
     "required": ["items"], "additionalProperties": False},
  "annotations": {"title": "Build a checkout link for the shopper", **RO}},
 {"name": "get_policies", "title": "Get store policies",
  "description": "Fetch the store's published refund, shipping, privacy and terms policies (plain-text excerpts plus URLs). Read-only.",
  "inputSchema": {"type": "object", "properties": {"store": _STORE, "which": {"type": "array", "items": {"type": "string", "enum": ["refund", "shipping", "privacy", "terms"]}}}, "additionalProperties": False},
  "annotations": {"title": "Get store policies", **RO}},
]
_cache = {}
def _fetch(url, ttl=300):
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl: return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/html"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r: body = r.read().decode("utf-8", "replace"); final = r.geturl()
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 2: raise
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, OSError):
            if attempt == 2: raise
            time.sleep(1.5 * (attempt + 1))
    _cache[url] = (time.time(), (body, final)); return body, final
def store_of(args):
    s = (args.get("store") or DEFAULT_STORE or "").strip().lower()
    s = re.sub(r"^https?://", "", s).split("/")[0]
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", s or ""): raise ValueError("store domain required, e.g. 'allbirds.com'")
    if DEFAULT_STORE and not ALLOW_ANY and s != DEFAULT_STORE: raise ValueError("this server is configured for " + DEFAULT_STORE)
    return s
def catalog(store, pages=4):
    if LOCKED and COLLECTIONS:
        seen, out = set(), []
        for c in COLLECTIONS:
            for p in range(1, pages + 1):
                prods = json.loads(_fetch(f"https://{store}/collections/{c}/products.json?limit=250&page={p}")[0]).get("products", [])
                out += [x for x in prods if x["id"] not in seen]; seen |= {x["id"] for x in prods}
                if len(prods) < 250: break
        return out
    out = []
    for p in range(1, pages + 1):
        body, _ = _fetch(f"https://{store}/products.json?limit=250&page={p}")
        prods = json.loads(body).get("products", [])
        out += prods
        if len(prods) < 250: break
    return out
def _base(store):
    return re.sub(r"(https://[^/]+).*", r"\1", _fetch(f"https://{store}/products.json?limit=1")[1])
def _summ(store, p, base):
    vs = p.get("variants", []); prices = [float(v["price"]) for v in vs if v.get("price")]
    return {"handle": p["handle"], "title": p["title"], "vendor": p.get("vendor"), "product_type": p.get("product_type"),
            "price_min": min(prices) if prices else None, "price_max": max(prices) if prices else None,
            "available": any(v.get("available") for v in vs), "variant_count": len(vs), "url": f"{base}/products/{p['handle']}"}
def search_products(a):
    store = store_of(a); q = [w for w in re.findall(r"[a-z0-9]+", (a.get("query") or "").lower()) if len(w) > 1]
    base = _base(store); res = []
    for p in catalog(store):
        tags = p.get("tags") or []; tags = tags if isinstance(tags, list) else str(tags).split(",")
        hay = " ".join([p.get("title", ""), p.get("product_type", ""), p.get("vendor", ""), " ".join(tags)]).lower()
        toks = set(re.findall(r"[a-z0-9]+", hay.replace("'", "")))
        score = sum(w in toks or (w.endswith("s") and w[:-1] in toks) or w + "s" in toks for w in q)
        if q and score < max(1, len(q) - 1): continue
        s = _summ(store, p, base)
        if a.get("in_stock_only", True) and not s["available"]: continue
        if a.get("max_price") is not None and (s["price_min"] is None or s["price_min"] > a["max_price"]): continue
        if a.get("min_price") is not None and (s["price_max"] is None or s["price_max"] < a["min_price"]): continue
        if a.get("product_type") and a["product_type"].lower() not in (s["product_type"] or "").lower(): continue
        tt = set(re.findall(r"[a-z0-9]+", s["title"].lower().replace("'", "")))
        res.append((score + 0.5 * sum(w in tt for w in q), s))
    res.sort(key=lambda x: -x[0]); lim = min(int(a.get("limit", 10)), 25)
    return {"store": store, "query": a.get("query"), "total_matches": len(res), "results": [s for _, s in res[:lim]],
            "note": "Searches the first 1,000 products of the public catalog."}
def get_product(a):
    store = store_of(a); base = _base(store); h = re.sub(r"[^a-z0-9-]", "", (a.get("handle") or "").lower())
    if LOCKED and COLLECTIONS and h not in {x["handle"] for x in catalog(store)}:
        raise ValueError(f"'{h}' is not in the products this connector offers")
    p = json.loads(_fetch(f"{base}/products/{h}.js", ttl=60)[0])
    return {"store": store, "handle": h, "title": p["title"], "vendor": p.get("vendor"), "url": f"{base}/products/{h}",
            "options": [o["name"] if isinstance(o, dict) else o for o in p.get("options", [])],
            "description": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p.get("description") or ""))).strip()[:800],
            "variants": [{"variant_id": v["id"], "title": v["title"], "price": v["price"] / 100, "compare_at_price": (v.get("compare_at_price") or 0) / 100 or None,
                          "available": v.get("available"), "sku": v.get("sku")} for v in p.get("variants", [])],
            "price_currency_note": "Prices are in the store's default currency. The shopper's checkout may localize them."}
def build_cart_link(a):
    store = store_of(a); base = _base(store); items = a.get("items") or []
    if not items: raise ValueError("items required")
    checked = []
    for it in items:
        vid = int(it["variant_id"]); qty = max(1, min(20, int(it.get("quantity", 1))))
        try: v = json.loads(_fetch(f"{base}/variants/{vid}.js", ttl=60)[0]); ok = True
        except urllib.error.HTTPError: v, ok = {}, False
        checked.append({"variant_id": vid, "quantity": qty, "exists": ok, "available": v.get("available"), "title": v.get("name") or v.get("title"),
                        "price": (v.get("price") or 0) / 100 if ok else None})
    bad = [c for c in checked if not c["exists"]]
    if bad: return {"store": store, "ok": False, "error": "unknown variant ids", "items": checked}
    link = f"{base}/cart/" + ",".join(f"{c['variant_id']}:{c['quantity']}" for c in checked)
    if REF: link += f"?ref={REF}&utm_source={REF}&utm_medium=ai_agent&utm_campaign=agent_cart"
    return {"store": store, "ok": True, "cart_url": link, "items": checked,
            "estimated_subtotal": round(sum((c["price"] or 0) * c["quantity"] for c in checked), 2),
            "instructions": "Give this link to the shopper. Opening it pre-fills the cart and goes to the store's own checkout, where they review it and pay. Nothing has been ordered.",
            "warnings": [f"variant {c['variant_id']} currently unavailable" for c in checked if c["available"] is False]}
POL = {"refund": "refund-policy", "shipping": "shipping-policy", "privacy": "privacy-policy", "terms": "terms-of-service"}
def get_policies(a):
    store = store_of(a); base = _base(store); out = {}
    for k in a.get("which") or ["refund", "shipping"]:
        url = f"{base}/policies/{POL[k]}"
        try:
            raw = json.loads(_fetch(url + ".json", ttl=3600)[0]).get("policy", {}).get("body", "")
            txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", raw, flags=re.S))).strip()
            out[k] = {"url": url, "excerpt": txt[:1500] or None}
        except urllib.error.HTTPError as e: out[k] = {"url": url, "error": f"HTTP {e.code}"}
    return {"store": store, "policies": out}
def tools():
    """Tool list. In merchant mode: store arg removed and descriptions branded with the store name."""
    if not LOCKED: return TOOLS
    import copy
    out = copy.deepcopy(TOOLS); scope = f" (collections: {', '.join(COLLECTIONS)})" if COLLECTIONS else ""
    for t in out:
        t["inputSchema"]["properties"].pop("store", None)
        t["description"] = f"Official {STORE_NAME} shopping tool for {DEFAULT_STORE}{scope}. " + t["description"].replace("the store's", f"{STORE_NAME}'s").replace("the merchant's", f"{STORE_NAME}'s")
        t["title"] = t["annotations"]["title"] = t["title"].replace("the store's", f"{STORE_NAME}'s").replace("store policies", f"{STORE_NAME} policies")
    return out
FUNCS = {"search_products": search_products, "get_product": get_product, "build_cart_link": build_cart_link, "get_policies": get_policies}
def handle(req):
    if not isinstance(req, dict) or req.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    mid, meth, p = req.get("id"), req.get("method"), req.get("params") or {}
    if "id" not in req: return None
    if meth == "initialize":
        v = p.get("protocolVersion"); v = v if v in SUPPORTED else SUPPORTED[0]
        r = {"protocolVersion": v, "capabilities": {"tools": {"listChanged": False}},
             "serverInfo": {"name": "shelfready", "title": f"{STORE_NAME} (ShelfReady)" if LOCKED else "ShelfReady", "version": VERSION},
             "instructions": "Use search_products, then get_product to pick a variant, then build_cart_link. Always hand the cart_url to the human to check out themselves. Never claim an order was placed."}
    elif meth == "ping": r = {}
    elif meth == "tools/list": r = {"tools": tools()}
    elif meth == "tools/call":
        f = FUNCS.get(p.get("name"))
        if not f: return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {p.get('name')}"}}
        try: data = f(p.get("arguments") or {}); err = False
        except (ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as e: data = {"error": str(e)}; err = True
        r = {"content": [{"type": "text", "text": json.dumps(data, indent=1)}], "structuredContent": data, "isError": err}
    else: return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {meth}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": r}
ALLOWED_ORIGINS = [o for o in os.environ.get("SHELFREADY_ALLOWED_ORIGINS", "https://claude.ai,https://claude.com,https://grok.com,https://muse.ai").split(",") if o]
class H(BaseHTTPRequestHandler):
    server_version = "shelfready/" + VERSION
    def _send(self, code, body=None):
        b = b"" if body is None else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/healthz": return self._send(200, {"ok": True, "store": DEFAULT_STORE or None, "locked": LOCKED, "collections": COLLECTIONS, "version": VERSION})
        self._send(405 if self.path.startswith("/mcp") else 404, {"error": "POST JSON-RPC to /mcp"})
    def do_DELETE(self): self._send(405, {"error": "stateless server; no sessions"})
    def do_POST(self):
        if not self.path.startswith("/mcp"): return self._send(404, {"error": "not found"})
        o = self.headers.get("Origin")
        if o and o not in ALLOWED_ORIGINS and not o.startswith(("http://localhost", "http://127.0.0.1")): return self._send(403, {"error": "origin not allowed"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 64_000: return self._send(413, {"error": "payload too large"})
        try: msg = json.loads(self.rfile.read(n) or b"null")
        except json.JSONDecodeError: return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        out = [r for r in map(handle, msg) if r] if isinstance(msg, list) else handle(msg)
        self._send(202) if not out else self._send(200, out)
if __name__ == "__main__":
    if "--http" in sys.argv:
        ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8788"))), H).serve_forever()
    else:
        for line in sys.stdin:
            if not line.strip(): continue
            try: out = handle(json.loads(line))
            except json.JSONDecodeError: out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            if out: print(json.dumps(out), flush=True)
