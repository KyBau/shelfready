import json, os, subprocess, sys, unittest, server, fixkit, csv
LIVE = os.environ.get("SHELFREADY_LIVE", "1") == "1"
def call(n, a): return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": n, "arguments": a}})["result"]
class Protocol(unittest.TestCase):
    def test_init(self):
        r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2026-07-28"}})["result"]
        self.assertEqual(r["protocolVersion"], "2026-07-28"); self.assertEqual(r["serverInfo"]["name"], "shelfready")
    def test_tools_annotated(self):
        t = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({x["name"] for x in t}, {"search_products", "get_product", "build_cart_link", "get_policies"})
        for x in t: self.assertTrue(x["annotations"]["readOnlyHint"]); self.assertFalse(x["annotations"]["destructiveHint"]); self.assertLessEqual(len(x["name"]), 64)
    def test_bad_store(self): self.assertTrue(call("search_products", {"store": "not a domain", "query": "x"})["isError"])
    def test_unknown(self): self.assertIn("error", server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "checkout"}}))
    def test_notification(self): self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    def test_stdio(self):
        out = subprocess.run([sys.executable, "server.py"], input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n', capture_output=True, text=True, timeout=10).stdout
        self.assertEqual(len(json.loads(out)["result"]["tools"]), 4)
class FixKit(unittest.TestCase):
    def test_ridge(self):
        row = {"domain": "ridge.com", "score": "100", "claude_score": "70", "claude_fetch_status": "403", "claude_fetch_readable": "False", "products_json": "200/5",
               "jsonld_product": "True", "llms_txt": "True", "storefront_mcp_tools": "1", "product_page": "200"}
        k = fixkit.kit(row, "Cloudflare", "wallets"); self.assertIn("cf.verified_bot_category", k); self.assertNotIn("schema.org Product markup", k)
    def test_jsonld_liquid(self): self.assertIn('"@type": "Offer"', fixkit.LIQUID)
@unittest.skipUnless(LIVE, "live")
class Live(unittest.TestCase):
    def flow(self, store, q):
        s = call("search_products", {"store": store, "query": q, "limit": 3}); self.assertFalse(s["isError"], s["structuredContent"]); res = s["structuredContent"]["results"]; self.assertTrue(res)
        p = call("get_product", {"store": store, "handle": res[0]["handle"]})["structuredContent"]
        v = next(x for x in p["variants"] if x["available"])
        c = call("build_cart_link", {"store": store, "items": [{"variant_id": v["variant_id"], "quantity": 2}]})["structuredContent"]
        self.assertTrue(c["ok"]); self.assertIn(f"/cart/{v['variant_id']}:2?ref=shelfready&utm_source=shelfready", c["cart_url"])
        self.assertTrue(call("get_policies", {"store": store, "which": ["refund"]})["structuredContent"]["policies"]["refund"].get("excerpt"))
        return c
    def test_allbirds(self): self.flow("allbirds.com", "mens wool runner")
    def test_taylorstitch(self): self.flow("taylorstitch.com", "linen shirt")
    def test_bad_variant(self): self.assertFalse(call("build_cart_link", {"store": "allbirds.com", "items": [{"variant_id": 1}]})["structuredContent"]["ok"])
def run_env(env, msgs):
    e = {**os.environ, **env}; e.pop("SHELFREADY_ALLOW_ANY_STORE", None) if "SHELFREADY_ALLOW_ANY_STORE" not in env else None
    out = subprocess.run([sys.executable, "server.py"], input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, timeout=60, env=e).stdout
    return [json.loads(l) for l in out.splitlines()]
class Merchant(unittest.TestCase):
    ENV = {"SHELFREADY_STORE": "allbirds.com", "SHELFREADY_STORE_NAME": "Allbirds", "SHELFREADY_REF": "shelfready"}
    def test_locked_branding(self):
        init, tl, other = run_env(self.ENV, [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
              {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_policies", "arguments": {"store": "evil.example.com"}}}])
        self.assertEqual(init["result"]["serverInfo"]["title"], "Allbirds (ShelfReady)")
        for t in tl["result"]["tools"]:
            self.assertNotIn("store", t["inputSchema"]["properties"]); self.assertTrue(t["description"].startswith("Official Allbirds shopping tool for allbirds.com"))
        self.assertTrue(other["result"]["isError"]); self.assertIn("configured for allbirds.com", other["result"]["content"][0]["text"])
    def test_demo_mode_opt_in(self):
        tl, = run_env({**self.ENV, "SHELFREADY_ALLOW_ANY_STORE": "1"}, [{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        self.assertIn("store", tl["result"]["tools"][0]["inputSchema"]["properties"])
    @unittest.skipUnless(LIVE, "live")
    def test_collections_filter_live(self):
        env = {**self.ENV, "SHELFREADY_COLLECTIONS": "mens-breathable-lightweight-tree-fiber-shoes"}
        s, bad = run_env(env, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_products", "arguments": {"query": "shoes", "in_stock_only": False, "limit": 25}}},
                               {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_product", "arguments": {"handle": "womens-wool-runners"}}}])
        res = s["result"]["structuredContent"]["results"]; self.assertTrue(res)
        self.assertTrue(all("Women" not in r["title"] for r in res), [r["title"] for r in res])
        self.assertTrue(bad["result"]["isError"])
if __name__ == "__main__": unittest.main(verbosity=2)
