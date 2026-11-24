# Submission form: ready-to-paste answers

These answers decide what the hidden benchmark tests, so they describe only what DealDesk actually does. Replace the URLs once you have deployed.

**Group:** G40 · **Track:** DealCloser · **Product name:** DealDesk

**Live website URL:** https://YOUR-PROJECT.vercel.app
**Agent API base URL:** https://YOUR-SPACE.hf.space (POST /chat, GET /health)
**GitHub repo:** https://github.com/YOUR-USER/dealdesk

---

### How does your agent work? (nodes)
LangGraph StateGraph with 7 nodes:
1. **guard**: deterministic safety screen. Refuses prompt injection, requests for other users' or agencies' data, and off-topic requests. Routes YES/NO replies to approval when an action is pending.
2. **qualifier**: extracts lead fields from the message (property or car, budget in lakh/crore, city, area, property type, car make/model, timeline, name, phone), scores the lead and saves them to long-term memory.
3. **matcher** (Matcher & Scheduler agent, claude-haiku-5-5): asks the one missing question, searches inventory, shows up to 3 matches, offers a site visit (property) or test drive (car), and saves preferences.
4. **tools**: executes tool calls for the current user_id only. Risky tools (book_visit, cancel_visit) are intercepted.
5. **approval**: human-in-the-loop. Asks "Please confirm … Reply YES or NO" and executes the booking or cancellation only after YES.
6. **followup**: schedules day 1/3/7 follow-ups for leads that haven't booked.
7. **refuse**: returns the refusal message.

### Tools
- `search_listings(category, max_price_pkr, city, area, property_type, make, model, min_year, transmission, keywords, limit)`: returns the top 3 matching listings from Postgres.
- `get_listing_details(listing_id)`: full specs and dealer of one listing.
- `book_visit(listing_id, datetime_iso, customer_name, customer_phone)`: validates the slot and asks the customer to confirm, then creates visit `V-<n>` (status "requested"; the dealer approves it in the dashboard).
- `cancel_visit(visit_id)`: the customer's own visits only, after confirmation.
- `my_visits()`: the customer's own bookings.
- `update_profile(...)`: saves name, phone, budget, area, model, timeline, preference or objection to long-term memory.
- `estimate_installment(price_pkr, down_payment_percent, years, annual_rate_percent, category)`: monthly installment estimate.

### Memory
- **Short-term:** LangGraph PostgresSaver checkpointer keyed by `user_id::thread_id`. It holds the messages, extracted fields, any pending action and a summary. After 16 messages, older turns are summarised.
- **Long-term:** `profiles` table in Neon Postgres keyed by `user_id`. It holds name, phone, category, budget, city/area, property type, car make/model, timeline, preferences, objections, listings viewed, and past visits. It is loaded into every conversation of that user. CNIC, card numbers and instructions are never stored.
- **Isolation:** user_id comes from the request, never from the model. Every query filters by user_id, and a user can never read another user's memory or bookings. Dealers see only their own agency's leads.

### Safety
- Refuses off-topic requests (poems, code, general knowledge) with a one-line redirect to property or cars.
- Refuses prompt injection ("ignore previous instructions", "show system prompt", "you are now…") and requests for other customers', leads' or agencies' data.
- Asks before risky actions: booking and cancelling visits need an explicit YES.
- Never invents listings or prices (answers only from tool results), never negotiates discounts, never asks for CNIC or bank details.

### Demo data (what testers can ask about)
- **Cars (prices in PKR):** Corolla GLi 2019 46 lakh (C-301), Corolla Altis 2020 54 lakh (C-302), Corolla Altis X 2022 59.5 lakh (C-303), Corolla Grande 2021 63 lakh (C-304), Civic Oriel 2021 78 lakh (C-305), Civic RS 2023 1.02 crore (C-306), City 2022 49 lakh (C-307), Alto 29 lakh, Swift 45 lakh, Sportage 84 lakh, Fortuner 1.65 crore, Haval H6 1.08 crore (Lahore, Prime Motors). Corolla 2021 57 lakh (C-401), Yaris 47 lakh, Civic 2019 52 lakh, City 38 lakh, Cultus 33 lakh, Wagon R 28 lakh, Tucson 79 lakh, MG HS 74 lakh, Elantra 66 lakh, Hilux 1.15 crore (Karachi, AutoHub).
- **Property:** DHA Phase 5 Lahore 1 kanal plot 2.75 crore (P-101), 10 marla plot 1.9 crore (P-102), 1 kanal house 7.5 crore. DHA Phase 6 house 4.6 crore. Bahria Town Lahore 5 marla plot 48 lakh (P-106), 10 marla plot 95 lakh (P-107), 5 marla house 1.85 crore, 1 bed apartment 72 lakh. Gulberg apartment 1.4 crore. Johar Town house 3.2 crore. Islamabad: Bahria Town Phase 8 10 marla plot 85 lakh (P-201), 1 kanal plot 1.9 crore, Phase 7 house 2.6 crore, DHA Phase 2 plot 4.1 crore, E-11 apartment 2.3 crore, G-13 plot 2.2 crore, Gulberg Greens plot 62 lakh, Bahria Enclave apartment 98 lakh.
- Visits and test drives can be booked daily from 10:00 to 19:00 Pakistan time, up to 60 days ahead.
- **Dealer logins:** skyline/skyline123, capital/capital123, prime/prime123, autohub/autohub123.
