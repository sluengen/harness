# Untrusted network fetch checklist

Load only when code fetches a URL derived from user input, third-party pages,
or page-declared content.

### Fetching untrusted URLs

The concrete application of `engineering-principles`' *Validate at boundaries, trust within* to the network-fetch boundary. When code issues a request to a URL drawn from untrusted content — a third-party page, a user-supplied link, a page-declared asset — the fetch itself is the boundary and the URL is hostile until proven otherwise. Before a batch or single fetch surface ships, it carries four checks:

1. **Scheme allowlist.** Accept `http`/`https` only for any URL derived from untrusted content; reject `file:`, `data:`, `gopher:`, and every other scheme outright.
2. **Host allowlist / reject internal addresses.** Refuse loopback, private, link-local, reserved, and cloud-metadata addresses (the SSRF surface) — an allowlist of expected hosts where one exists, an explicit denylist of those ranges otherwise.
3. **Download size cap.** Stream the body and abort once it passes a byte cap; never buffer a whole untrusted response into memory.
4. **Decompression / pixel cap; re-validate after redirects.** Bound the *decoded* size of compressed or media payloads (a decompression and pixel cap, not just the wire size), and re-run checks 1–2 on the final URL after every redirect — a redirect target is as untrusted as the original.

The principle has one home in `engineering-principles`; this checklist is its build-time application at the fetch boundary, so the reviewer (`review-discipline`, which shares this file's bar) and the next fetch surface both get a concrete bar by default.

---
