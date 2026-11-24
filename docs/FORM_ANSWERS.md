# Submission form: ready-to-paste answers

Group G40 · Track 3, DealCloser · Product: **DealDesk**

---

## 1. One-line pitch
DealDesk is a 24/7 AI sales assistant for Pakistani real-estate agencies and car dealers: it qualifies buyers, shows matching listings and books site visits / test drives. Dealers pay a monthly subscription plus Rs 1,000 per booked visit.

## 2. Links

**Live website URL (customer page + dashboard):**
Customer page: https://dealdesk-frontend.vercel.app · Dealer dashboard: https://dealdesk-frontend.vercel.app/admin (logins: `prime / prime123`, `skyline / skyline123`, `capital / capital123`, `autohub / autohub123`)

**Agent API base URL:**
https://dealdesk-api-hyz7.onrender.com

**Public GitHub repo URL:**
https://github.com/AbdullahBinNasir16/dealdesk

**Link to tests.json:**
https://github.com/AbdullahBinNasir16/dealdesk/blob/main/tests.json

**Demo video link:** _(add your YouTube unlisted / Drive link)_

**Photo of paper canvas:** _(add your Drive link)_

**Where is your agent API hosted?** Render

## 3. How your agent works

**LangGraph design (nodes):**
A LangGraph StateGraph with 7 nodes. Checkpoints are stored in Postgres.
1. **guard** (0 tokens): a regex safety screen. It refuses prompt injection, requests for other users' or agencies' data, and off-topic asks before any LLM call. When a booking is pending, it routes YES/NO replies (English and Roman Urdu, e.g. "haan ji") to approval.
2. **qualifier** (0 tokens): extracts lead fields. These are property or car, budget in lakh/crore converted to PKR, city, area, property type, car make/model, transmission, timeline, name and phone. It scores the lead and writes long-term memory.
3. **matcher** (claude-haiku-5-5, thinking off, low effort, cached system prompt): the tool-calling sales agent. It asks one missing question, searches, shows up to 3 real matches and offers a site visit or test drive. It is capped at 4 tool steps per turn.
4. **tools**: runs tools using the `user_id` from the graph state, never from the model. Risky tools (book_visit, cancel_visit) only validate and park a pending action.
5. **approval** (human-in-the-loop, 0 tokens): asks "Please confirm … Reply YES or NO" and executes the booking or cancellation only after YES.
6. **followup** (0 tokens): schedules day 1/3/7 follow-up messages for leads that didn't book. Booking cancels them.
7. **refuse**: returns the guard's refusal message.

Flow: START → guard → (refuse | approval | qualifier → matcher ⇄ tools → approval or followup) → END.

**Tools (input → output):**
- `search_listings(category, max_price_pkr, min_price_pkr, city, area, property_type, car_type, make, model, min_year, transmission, keywords, limit)` → up to 3–5 active listings (id, title, price, location, key specs, dealer) and the total match count. If nothing fits, it relaxes the filters and says so in a note (e.g. "closest options slightly above budget").
- `get_listing_details(listing_id)` → full specs, description, price, dealer name and phone, and visit type.
- `book_visit(listing_id, datetime_iso, customer_name?, customer_phone?)` → validates the slot (future, 10:00–19:00 Pakistan time, at most 60 days ahead, no clash, no duplicate) and returns "awaiting_customer_confirmation". After YES, it creates visit `V-<n>` with status "requested" for the dealer to approve.
- `cancel_visit(visit_id)` → the customer's own visit only. It needs YES, then the visit is cancelled.
- `my_visits()` → the customer's own bookings (ref, listing, time, status).
- `update_profile(preference?, objection?, …)` → saves preferences or objections to long-term memory and returns the saved keys.
- `estimate_installment(price_pkr, down_payment_percent, years, annual_rate_percent?, category)` → monthly installment in Rs, the down payment, the financed amount, and an "estimate only" note.

**Demo data and example requests:**
44 listings from 4 dealers. Property agencies: Skyline (Lahore) and Capital (Islamabad). Car showrooms: Prime Motors (Lahore) and AutoHub (Karachi). IDs are P-1xx/P-2xx for property and C-3xx/C-4xx for cars. Example requests:
- "Corolla under 60 lakh" → C-303 (59.5 lakh), C-401 (57), C-302 (54), C-301 (46)
- "DHA Phase 5 plot under 3 crore, buying in 2 months" → P-101 (2.75 crore), P-102 (1.9 crore)
- "Automatic SUV in Karachi under 85 lakh" → C-408 MG HS (74 lakh), C-407 Tucson (79 lakh)
- "Book a test drive for C-303 this Saturday at 4 PM" → asks to confirm; "yes" → "Booked! … Reference: V-12"
- "Monthly installment for C-302 with 30% down over 5 years" → estimate in Rs

Roman Urdu also works, e.g. "mujhe Lahore mein 50 lakh tak automatic gaari chahiye".

**Short-term memory:**
Each `user_id::thread_id` has its own LangGraph PostgresSaver checkpoint. It keeps:
- the message history
- fields extracted in this chat
- any pending booking awaiting YES/NO
- a running summary

So "which one is the cheapest?", "only under 1 crore" and "book it" refer back to earlier turns. For long chats, once a thread passes 16 messages, the older turns are summarised by the model into a short memory note and removed. The latest ~6 messages stay verbatim. Our 9-turn test still recalls the first message.

**Long-term memory:**
Saved per `user_id`, across all threads:
- name and phone
- property or car
- budget
- city/area and property type
- car make/model and transmission
- timeline
- preferences and objections
- listings viewed
- past visits

It is loaded into every new conversation, so a returning user isn't asked again and a booking is pre-filled with their saved name. **Not saved:** CNIC, card or bank numbers (stripped), injected instructions (filtered), or full chat transcripts (those stay in the per-thread checkpoint).

**Where is long-term memory stored?** Hosted Postgres (Neon). This is the `profiles` table; LangGraph checkpoints are in the same Neon database.

**User isolation:**
- Every tool gets `user_id` from the graph state (the request), never from the model, and every query filters on it. A user can only see, book or cancel their own visits. Cancelling someone else's V-number returns "not found".
- Checkpoints are keyed `user_id::thread_id`, so two users sending the same `thread_id` never share a conversation.
- The guard refuses requests for other customers' or agencies' data before the LLM runs.
- The dealer dashboard uses signed tokens. Each agency sees only its own leads, visits, chats and listings; another agency's IDs return 404.

**Safety:**
- **Off-topic** (poems, code, homework, general knowledge): a polite one-line refusal and a redirect to property/cars. The regex guard does this at 0 tokens, and the system prompt is a second layer. For example, "write a Python script that scrapes car prices" is refused by the model.
- **Prompt injection** ("ignore previous instructions", "repeat your system prompt", "you are now DAN", fake `</system>` tags, SQL strings): refused by the guard at 0 tokens. Tool results are treated as data.
- **Risky actions:** booking and cancelling are split into validate and execute. The customer must reply YES (or "haan ji") before anything is written. The dealer then approves the visit in the dashboard.
- **Never:** invents listings or prices, promises discounts, or asks for CNIC or card details.
- **Abuse limits:** 2,000-character message cap, 40 messages per minute per user, 4 agent steps per turn, 600 max output tokens.

**Your own benchmark result:**
BENCHMARK_RESULT

**Known limitations:**
- Render free tier: after 15 minutes idle, the first request takes about 50 seconds to wake the server. After that, turns take about 1–3 seconds.
- Demo inventory only (44 listings). Bookings are "requested" until a dealer approves them in the dashboard. No real SMS or WhatsApp is sent; the day 1/3/7 follow-ups are shown in the dashboard to be sent manually.
- Free-text dates such as "this Saturday 4 PM" are converted by the model using the current Pakistan time in its prompt.

## 4. Declaration
Tick all five. This is true for our repo: the only key is in the Render environment variables, `.env` is git-ignored, and a secret scan of the repo found no keys.
