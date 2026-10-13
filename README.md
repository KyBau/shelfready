# ShelfReady: make any Shopify store shoppable by Claude, Grok and Muse

**Problem (from our 25-brand audit, Oct 13 2026):** robots.txt doesn't block anyone. But Shopify's default storefront MCP exposes one tool (policies FAQ). Edge bot rules quietly block agents: Ridge returns 403 to a Claude-User UA. Headless stores hide their catalog: Bombas returned 429 on products.json. Some stores have no schema.org Product markup (Gymshark).

**Solution, part 1: ShelfReady MCP server** (`server.py`, zero dependencies, stateless, MCP 2026-07-28). Four read-only tools over a store's public catalog:
| Tool | What it does |
|-|-|
| `search_products` | query plus max/min price, product_type, in-stock filters (first 1,000 products) |
| `get_product` | variants with id, size/options, price, compare-at, availability, SKU |
| `build_cart_link` | variant ids + qty → validated `https://store/cart/<id>:<qty>` permalink. The **human checks out on the merchant's site**. No payment, no order placed. |
| `get_policies` | refund/shipping/privacy/terms excerpts from `/policies/*.json` |
All tools have `readOnlyHint: true` and `destructiveHint: false`. There's no auth, and no user data is stored or logged. Origins are allow-listed (Claude, Grok, Muse). That matches CancelPath's Claude-directory posture.

**Solution, part 2: Fix-kit generator** (`fixkit.py`). It turns audit rows into a merchant to-do list: Cloudflare WAF skip rule for verified AI agents, Vercel firewall steps, a schema.org ProductGroup snippet (Liquid + Next.js/Hydrogen), an llms.txt template, and curl verify steps. Sample kits: `fixkits/ridge.md`, `fixkits/bombas.md`, `fixkits/gymshark.md`.

## Merchant install (single-store mode)
Setting `SHELFREADY_STORE` **locks the server to that store by default**:
- The `store` argument disappears from every tool, and calls for any other domain are refused.
- Tool titles and descriptions are branded, e.g. "Official Allbirds shopping tool for allbirds.com…". serverInfo title is "Allbirds (ShelfReady)".
- `SHELFREADY_COLLECTIONS=handle1,handle2` (optional) limits search and get_product to those collections.
- Cart links carry attribution: `https://store/cart/<variant>:<qty>?ref=shelfready&utm_source=shelfready&utm_medium=ai_agent&utm_campaign=agent_cart`. This shows up in Shopify analytics and the order's landing page. Change the tag with `SHELFREADY_REF`, or set it empty to disable.

| Env | Meaning |
|-|-|
| `SHELFREADY_STORE` | merchant domain (required for merchant mode) |
| `SHELFREADY_STORE_NAME` | display name for branding (default: derived from domain) |
| `SHELFREADY_ALLOW_ANY_STORE` | `1` = multi-store demo; default `0` when a store is set |
| `SHELFREADY_COLLECTIONS` | optional collection handles |
| `SHELFREADY_REF` | attribution tag (default `shelfready`) |

Install options:
1. **Hosted by us (paid):** you get `https://<store>.shelfready…/mcp`. We set it up and submit it to Claude's directory, Grok custom connectors and Muse.
2. **Self-host:** Render → New → Blueprint → this repo. Set the env vars above. Health check: `/healthz`.
3. **Local:** `SHELFREADY_STORE=yourstore.com python3 server.py` (stdio).
Fix kit: `python3 fixkit.py results.csv '{"yourstore.com":"Cloudflare"}' '{"yourstore.com":"what you sell"}'`.

## Pricing hypothesis (untested)
- Free: audit + fix kit (lead gen). Use the audit thread for distribution.
- $49–99/mo: hosted connector, directory submissions, weekly re-audit + alerts when an edge rule starts blocking agents.
- $500 one-time: done-for-you fixes (WAF rule, JSON-LD, llms.txt).
- Later: revenue share / affiliate on agent-originated carts (tag cart links with `?ref=`). This needs merchant agreement and is not built.

## Tests
`python3 test_server.py`: 14 tests (incl. merchant lock/branding/collections) (protocol, annotations, stdio, fix kit, live Allbirds + Taylor Stitch flows). Set `SHELFREADY_LIVE=0` to skip network tests.
Demo: `demo_transcript.json` (real live run, 2026-10-13 1:36 AM CT), image `make_demo_png.py` → `/workspace/connector-products/shelfready-demo.png`.

## Limits
Works only where `/products.json` is public. That rules out headless/locked stores like Bombas, SKIMS and Ruggable until they use the fix kit. Prices come in the store's default currency. Cart permalinks don't guarantee stock. Not deployed. No partner agreements with Shopify or any merchant.
