// Static-asset Cloudflare Worker for c3000.iamfatness.us — the Coordinator3000
// documentation + console demo. Serves ./public with hardened security headers,
// trailing-slash normalization, and a directory-index fallback.

const SECURITY_HEADERS = {
  // script-src 'self' — all JS is external (demo/app.js); no inline scripts.
  // style-src allows inline styles used by the landing/demo markup.
  "content-security-policy":
    "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; " +
    "script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; " +
    "base-uri 'self'; form-action 'self'",
  "referrer-policy": "strict-origin-when-cross-origin",
  "x-content-type-options": "nosniff",
  "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
};

function withHeaders(response) {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(SECURITY_HEADERS)) {
    headers.set(key, value);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function fetchAsset(request, env, pathname) {
  const url = new URL(request.url);
  url.pathname = pathname;
  return env.ASSETS.fetch(new Request(url, request));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    let response = await env.ASSETS.fetch(request);
    if (response.status !== 404) {
      return withHeaders(response);
    }

    // Redirect extension-less paths to their trailing-slash form.
    if (!url.pathname.endsWith("/") && !url.pathname.includes(".")) {
      url.pathname += "/";
      return Response.redirect(url.toString(), 301);
    }

    // Serve directory index documents (e.g. /demo/ -> /demo/index.html).
    if (url.pathname.endsWith("/")) {
      response = await fetchAsset(request, env, `${url.pathname}index.html`);
      if (response.status !== 404) {
        return withHeaders(response);
      }
    }

    return withHeaders(new Response("Not found", { status: 404 }));
  },
};
