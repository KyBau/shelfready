# ShelfReady fix kit: bombas.com
Audit run 2026-10-13 (agent_readiness). Overall score 20/100, Claude-readiness 40/100. Edge: Vercel (server: Vercel; headless).

## 1. P0 - Make your catalog machine-readable
Observed: /products.json returned 429. Edge: Vercel (server: Vercel; headless).

```
Vercel -> Project -> Firewall:
1. Check for a custom rule or rate limit matching /products.json, or a 'Bot Protection' / 'Attack Challenge Mode' setting. A plain curl got HTTP 429 on /products.json.
2. Add a custom rule above it: IF path starts with /products OR /policies OR /cart, AND user-agent matches (ClaudeBot|Claude-User|Claude-SearchBot|GPTBot|ChatGPT-User|OAI-SearchBot|PerplexityBot), THEN Bypass (or raise the rate limit to ~60 req/min per IP).
3. Headless storefronts don't serve Shopify's /products.json by default. Proxy it to the Shopify origin, or expose an equivalent catalog route, so agents get a machine-readable catalog.
```

## 2. P1 - Add schema.org Product markup
Not verified: the audit couldn't reach a product page. Check that your product template emits this markup.

```
// Headless (Next.js / Hydrogen) equivalent. Render this in the product page component.
export function ProductJsonLd({ product, origin }) {
  const data = {
    "@context": "https://schema.org", "@type": "ProductGroup", name: product.title,
    description: product.description?.slice(0, 500), url: `${origin}/products/${product.handle}`,
    brand: { "@type": "Brand", name: product.vendor }, productGroupID: String(product.id),
    hasVariant: product.variants.map(v => ({ "@type": "Product", sku: v.sku, name: v.title,
      offers: { "@type": "Offer", price: Number(v.price.amount ?? v.price), priceCurrency: v.price.currencyCode ?? "USD",
        availability: `https://schema.org/${v.availableForSale ?? v.available ? "InStock" : "OutOfStock"}` } })),
  };
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
}

--- Liquid version (Online Store 2.0 themes) ---
{%- comment -%} ShelfReady: schema.org Product JSON-LD. Put this in sections/main-product.liquid (or snippets/shelfready-jsonld.liquid and render it there). {%- endcomment -%}
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ProductGroup",
  "name": {{ product.title | json }},
  "description": {{ product.description | strip_html | truncate: 500 | json }},
  "url": {{ shop.url | append: product.url | json }},
  "brand": {"@type": "Brand", "name": {{ product.vendor | json }}},
  "productGroupID": {{ product.id | json }},
  "image": {{ product.featured_image | image_url: width: 1200 | prepend: 'https:' | json }},
  "hasVariant": [
    {%- for v in product.variants -%}
    {
      "@type": "Product",
      "sku": {{ v.sku | json }},
      "name": {{ v.title | json }},
      {%- if v.barcode != blank -%}"gtin": {{ v.barcode | json }},{%- endif -%}
      "offers": {
        "@type": "Offer",
        "url": {{ shop.url | append: v.url | json }},
        "price": {{ v.price | divided_by: 100.0 | json }},
        "priceCurrency": {{ cart.currency.iso_code | json }},
        "availability": "https://schema.org/{% if v.available %}InStock{% else %}OutOfStock{% endif %}"
      }
    }{% unless forloop.last %},{% endunless %}
    {%- endfor -%}
  ]
}
</script>
```

## 3. P1 - Publish /llms.txt
Observed: no llms.txt.

```
Serve this at https://bombas.com/llms.txt (Shopify: Online Store -> Navigation -> URL redirect to a page, or a headless route):

# Bombas
> Bombas sells socks, underwear and apparel. AI agents may browse our public catalog and hand shoppers a cart link; checkout happens on bombas.com.

## Shop
- Catalog (JSON): https://bombas.com/products.json
- Product JSON: https://bombas.com/products/{handle}.js
- Cart link format: https://bombas.com/cart/{variant_id}:{qty},{variant_id}:{qty}
- Agent connector (MCP): https://<your-shelfready-host>/mcp

## Policies
- Returns: https://bombas.com/policies/refund-policy
- Shipping: https://bombas.com/policies/shipping-policy

## Rules for agents
- Never place orders or enter payment details; give the shopper the cart link.
- Quote prices and availability from the product JSON, not from cached text.

```

## 4. P2 - Give agents real shopping tools (ShelfReady connector)
Observed: Shopify storefront MCP tools exposed = 0 (policies FAQ only, if any).

```
Run ShelfReady with SHELFREADY_STORE=bombas.com SHELFREADY_ALLOW_ANY_STORE=0 to expose search_products, get_product, build_cart_link and get_policies. Then submit it to Claude's directory (community tier), Grok custom connectors and Muse.
```

## Verify after shipping
```
curl -s -o /dev/null -w '%{http_code}\n' -A 'Mozilla/5.0 (compatible; Claude-User/1.0; +Claude-User@anthropic.com)' https://bombas.com/
curl -s 'https://bombas.com/products.json?limit=1' | head -c 200
python3 agent_readiness/audit.py <(echo bombas.com)
```
Note: a UA-only test can't prove Claude's real IPs pass. Check your Cloudflare/Vercel logs for verified ClaudeBot hits too.