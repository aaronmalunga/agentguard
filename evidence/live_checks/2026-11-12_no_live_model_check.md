# Live check after removing the Gemini key (option C), 12 Nov 2026, ~09:57 SA

Deployed commit `9f11ca6` on https://agentguard-jg01.onrender.com, after `GEMINI_API_KEY` was removed in Render.
Checked by Claude from the built-in browser on Aaron's laptop (own demo session, reset first). One run each.

| Check | Seen | Result |
|---|---|---|
| `/healthz` | `live_ai: false`; market Channel3; webhooks on (PayPal-verified) | Pass |
| Header chip (after a page reload) | "AI: saved answers" | Pass |
| "Draft my rules" | Button off; note "Live drafting is off on this demo. See "Rules in force"." No error toast | Pass |
| Six scenarios | normal → captured; poisoned → blocked; inflated → held; out-of-stock swap → held; agent lies → asked first; mislabelled → asked first. All replayed saved answers (recorded 9 Nov; mislabelled 11 Nov) | Pass |
| Draft API called directly | 503 `ai_unavailable` (expected: nothing to draft with) | Pass |

Notes:
- A browser that had the old page cached kept showing the model name until reloaded. First-time visitors get the new page.
- Later that morning the free server slept and woke while a video take was in progress (no deploy after 09:55), wiping the
  demo data; two PayPal refund webhooks then arrived for a payment that no longer existed and were counted as
  `unmatched`, changing nothing. The pinger (cron-job.org, https URL) must be on before submission.
