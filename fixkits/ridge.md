# ShelfReady fix kit: ridge.com
Audit run 2026-10-13 (agent_readiness). Overall score 100/100, Claude-readiness 70/100. Edge: Cloudflare (server: cloudflare, cf-ray observed).

## 1. P0 - Let Claude reach your product pages
Observed: product pages return HTTP 403 to a Claude-User user agent and 200 to a normal browser. Edge: Cloudflare (server: cloudflare, cf-ray observed).

```
Cloudflare -> Security -> WAF -> Custom rules -> Create rule (put it ABOVE any bot-blocking rule)
Name: ShelfReady - allow verified AI agents
Expression:
  (cf.client.bot) or (cf.verified_bot_category in {"AI Assistant" "AI Search" "AI Crawler"})
Action: Skip -> All remaining custom rules, Rate limiting rules, Managed rules, Super Bot Fight Mode
Also: Security -> Bots -> AI Crawl Control (or "Block AI bots"): set Claude-User / ChatGPT-User / Perplexity-User (user-triggered fetches) to Allow.
Note: the verified-bot check depends on Cloudflare's IP verification, so spoofed user agents stay blocked. Check the field and category names in your dashboard before saving.
```

## 2. P2 - Give agents real shopping tools (ShelfReady connector)
Observed: Shopify storefront MCP tools exposed = 1 (policies FAQ only, if any).

```
Run ShelfReady with SHELFREADY_STORE=ridge.com SHELFREADY_ALLOW_ANY_STORE=0 to expose search_products, get_product, build_cart_link and get_policies. Then submit it to Claude's directory (community tier), Grok custom connectors and Muse.
```

## Verify after shipping
```
curl -s -o /dev/null -w '%{http_code}\n' -A 'Mozilla/5.0 (compatible; Claude-User/1.0; +Claude-User@anthropic.com)' https://ridge.com/
curl -s 'https://ridge.com/products.json?limit=1' | head -c 200
python3 agent_readiness/audit.py <(echo ridge.com)
```
Note: a UA-only test can't prove Claude's real IPs pass. Check your Cloudflare/Vercel logs for verified ClaudeBot hits too.