// SCRS Groq relay — a tiny Cloudflare Worker that forwards the bot's Groq
// API calls to api.groq.com from Cloudflare's network.
//
// Why: Groq's edge blocks requests from some datacenter IP ranges
// (Katabump's included) with 403 "Access denied. Please check your network
// settings." — before it even checks the API key. Routing the calls through
// this Worker makes them arrive from Cloudflare IPs instead, which Groq
// accepts. The relay holds NO Groq key — it forwards the bot's own
// Authorization header untouched.
//
// Setup (about 2 minutes, free, no card):
//   1. Go to https://dash.cloudflare.com → sign up / log in
//   2. Workers & Pages → Create → Worker → name it e.g. "scrs-groq-relay" → Deploy
//   3. Edit code → delete the template → paste THIS file in → Deploy
//   4. Worker → Settings → Variables and Secrets → add a secret:
//        RELAY_KEY = <make up a long random password>
//   5. In the bot's Katabump .env set:
//        GROQ_BASE_URL=https://scrs-groq-relay.<your-subdomain>.workers.dev/openai/v1
//        GROQ_RELAY_KEY=<the same password from step 4>
//   6. Restart the bot, then check /sysinfo — "Groq API" should show ✅ 200.

export default {
  async fetch(request, env) {
    // Only the bot (which knows the shared secret) may use this relay.
    if (!env.RELAY_KEY || request.headers.get("X-Relay-Key") !== env.RELAY_KEY) {
      return new Response("Unauthorized", { status: 401 });
    }

    const incoming = new URL(request.url);
    const target = "https://api.groq.com" + incoming.pathname + incoming.search;

    const headers = new Headers(request.headers);
    headers.delete("X-Relay-Key"); // don't leak the relay secret to Groq
    headers.delete("host");

    const init = { method: request.method, headers };
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body; // streams JSON and audio uploads through
    }
    return fetch(target, init); // streams the response (incl. TTS WAV) back
  },
};
