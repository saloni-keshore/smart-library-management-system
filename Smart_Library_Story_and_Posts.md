# Smart Library — Story + LinkedIn Posts

Cross-checked against two sources:
1. **`LINKEDIN_POST_INFO.md`** — facts pulled from the actual codebase (`docs/`, routes, database).
2. **`Smart_Library_LinkedIn_Info.md`** — messaging + context from your chats (GPT).

---

## Part 1 — Do the two files agree?

Mostly yes. They describe the same product from two angles: the outreach file is *how you talk
about it*, the codebase file is *what is actually built*. Reconciled picture:

| Point | Chat file (GPT) | Codebase file (reality) | Use in posts |
|---|---|---|---|
| Name | "Smart Library" | "Smart Library App" | **Smart Library**. "Smart6" in your last message was a typo — ignore it. |
| Who it's for | Libraries, self-study centres | Coaching-centre / reading-library business, multi-tenant (each owner sees only their own data) | "Libraries and self-study centres" is fine. |
| Admissions, memberships, fees, renewals, records | Listed | All implemented (enquiry → admission → membership → payment) | Safe to claim. |
| Seat allocation | "Seat allocation" | Implemented as **time-window shift slots** with per-slot pricing (morning/evening/night rates) | Say "seat / shift-slot management" — it's real. |
| Cashbook | Listed | Full income/expense ledger + manual entries + audit log | Safe to claim. |
| Reports | Listed | Currently a **Business Intelligence dashboard**: health score, growth trend, top revenue sources, ranked action items. The old "Reports" page redirects here. | Say "reports and insights" — don't promise custom report builder. |
| Renewal reminders / notifications | Not claimed | Membership-expiry buckets shown in-app + a navbar bell. **No SMS / WhatsApp / email sending exists.** | Say "expiry alerts inside the app." Do **not** claim messaging. |
| Assistant / AI | GPT says don't claim AI | There is a built-in assistant ("Panda") but it is **rule-based** — fixed templates + your real numbers, no ML, no LLM | You may mention "a built-in assistant that answers questions from your real data." **Never call it AI.** |
| Stack | Supabase + Vercel | Flask (Python) + Supabase/Postgres + Chart.js, deployed on Vercel, no ORM | Safe, but keep it light for LinkedIn. |

**Still do NOT claim** (neither file supports it): pricing, number of customers, launch date, a
mobile app, payment-gateway / biometric / WhatsApp / SMS / email integrations, book-catalogue or
issue-return features, testimonials, or any "AI / ML" capability.

---

## Part 2 — The story (the through-line for every post)

Libraries and self-study centres still run on paper registers and a pile of Excel sheets. One
sheet for admissions, another for who paid, a third for which seat or shift is taken, and a
mental note for whose membership expires this week. Nothing talks to anything else, so the owner
spends the evening reconciling instead of growing the place.

The insight behind Smart Library is that all of this is actually **one connected flow**: a person
enquires, takes admission, picks a membership and a shift slot, pays a fee, renews later, and
every rupee of that lands in a cashbook that should roll straight up into a simple health report.
If you build that one flow properly, the registers and the Excel sheets just disappear.

So that's what I'm building — as a founder, in the open. Small stack, honest scope: it does
admissions, memberships, seats/shift slots, fee collection, renewals, member records, a cashbook,
and a reports-and-insights dashboard, all in one place, with each library's data kept separate.
I'd rather ship the boring, useful core and talk to real library owners than demo a feature list
that isn't real yet.

---

## Part 3 — Posts (5, ready to edit)

Voice: Saloni, founder, build-in-public. Keep line breaks as-is when pasting.

---

### Post 1 — Why I started (the problem)

I'm Saloni, and I'm building **Smart Library** — software to run the day-to-day operations of a
library or self-study centre (the paid-seat reading halls where students buy a monthly seat to
study).

Here's why.

Almost every one of these places I've spoken to still runs on a paper register and 4–5 Excel
sheets.

One sheet for admissions.
One for fees.
One for who's sitting on which seat or shift.
And a rough mental list of whose membership expires this week.

None of them talk to each other. So the owner ends up doing "data entry about their own
business" every night instead of actually running it.

That's what Smart Library is for: bring admissions, memberships, seats, fees, renewals, member
records and the cashbook into one simple system, so the registers and the Excel sheets can go
away.

If you run a library or study centre, I'd genuinely like to hear how you manage this today.

#BuildInPublic #Libraries #StartupJourney

---

### Post 2 — Feature spotlight: seats + renewals

Two things every study-centre owner tracks manually, and both are painful:

**1. Who is sitting where, and in which shift.**
Morning batch, evening batch, night — different students, sometimes different rates. On paper
this is a mess of cutting and re-writing.

**2. Whose membership is about to end.**
Miss it, and a paying member just quietly stops coming.

In Smart Library both are built in. Seats and shift slots are assigned in the app with their own
pricing, and memberships that are expiring show up as alerts on the dashboard — so renewals
become a task you can see, not something you remember by luck.

Still early, still improving it with feedback from real libraries.

#BuildInPublic #ProductUpdate #Libraries

---

### Post 3 — Feature spotlight: money clarity (cashbook + reports)

Ask a library owner "how did this month go?" and the honest answer is often "I think it was
okay?"

Not because they don't care — because the numbers are spread across a fee register, a rough
expense diary and memory.

Smart Library keeps a proper **cashbook**: every admission and renewal payment goes in
automatically, expenses are added in a click, and it rolls up into a simple dashboard — revenue
trend, top sources of income, and a short list of things worth acting on this week.

The goal isn't fancy analytics. It's for an owner to open one screen and actually know where
they stand.

#BuildInPublic #SmallBusiness #Libraries

---

### Post 4 — Build-in-public: how I'm building it

A few principles I'm holding myself to while building **Smart Library**:

**One connected flow, not a feature pile.**
Enquiry → admission → membership → seat/shift → fee → renewal → cashbook → report. Each step
feeds the next. That's the whole point.

**Move carefully with data.**
I migrated the database over one table at a time, with each step double-checked, instead of one
risky big switch. Library data is someone's livelihood.

**No buzzword inflation.**
There's a built-in assistant that answers questions from your real numbers — and I deliberately
don't call it "AI," because it isn't. It does what it says, nothing more.

Building in public means you can hold me to all three.

#BuildInPublic #Flask #Supabase #StartupJourney

---

### Post 5 — Outreach: looking for pilot libraries

Hi — I'm Saloni, and I'm building **Smart Library**, a management platform for libraries and
self-study centres.

It handles admissions, memberships, seat and shift allocation, fee collection, renewals, member
records, cashbook and reports — in one simple system, so you're not living in registers and
Excel.

I'm now looking for a few libraries to try it and tell me what's missing.

No cost, no long pitch — I just want honest feedback from people who run this every day.

If that's you, or you know someone, comment or DM me.

#BuildInPublic #Libraries #SelfStudy #Feedback

---

### Bonus Post 6 — A lesson (optional, use later)

Early lesson from building **Smart Library**:

Owners don't ask for "features." They ask for their evening back.

"Can I stop re-writing the seat chart every week?"
"Can I know who hasn't renewed without checking every page?"
"Can I see this month's money on one screen?"

Every time I've chased something flashier than that, it was the wrong call. The boring, connected
core is the product.

#BuildInPublic #ProductLessons #StartupJourney
