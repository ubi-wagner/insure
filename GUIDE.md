# Insure — Quick Start Guide

## What Is This?

Insure is your lead generation command center for Florida condo insurance.
You draw regions on a map, the system hunts for properties, and when you
find one you like, it analyzes their insurance docs and writes outreach
emails for you.

The workflow is: **Hunt → Kill → Cook**

- **Hunt**: Find condo/HOA properties in a target area
- **Kill**: Extract their insurance intel (carrier, premium, expiration)
- **Cook**: Generate personalized outreach emails

---

## Step 1: Log In

Go to your portal URL and sign in with your credentials.

---

## Step 2: Target a Region

You'll land on the dashboard. The map is centered on Tampa.

1. **Navigate**: Type a zip code or address in the search bar (top-left
   of map) and click **Go**
2. **Draw**: Click the **rectangle tool** in the top-center of the map
3. **Select area**: Click and drag to draw a blue box around the
   neighborhood you want to target
4. **Fill out the form** that pops up:
   - **Region Name** — give it a name like "Clearwater Beach Condos"
   - **Min Stories** — minimum building height (default 3)
   - **Max Coast Distance** — how far inland in miles (default 5)
5. Click **Start Hunt**

The hunter agent will start crawling for properties in that area. You'll
see leads appear in the pipeline below.

---

## Step 3: Review Leads

Below the map, lead cards appear as the hunter finds properties. Each
card shows:

- Satellite image of the property
- Property name, address, county
- Status badge: **New**, **Candidate**, or **Rejected**

### Sorting

Use the **Date** and **Coast Proximity** buttons to sort leads.

### Voting

Each card has two buttons:

- **Hunt** (green) — Marks the property as a Candidate and kicks off
  the AI analysis (Kill + Cook)
- **Reject** (red) — Removes it from consideration

---

## Step 4: View Insurance Intel & Emails

After you click **Hunt** on a lead, the AI analyzes any available
documents and extracts:

- Insurance carrier name
- Annual premium
- Policy expiration date
- Decision maker name
- Key risks

This intel appears on the card. **Click the card** to open the detail
view, where you'll see:

- Full insurance intelligence breakdown
- **4 pre-written outreach emails**:
  - **Informal** — friendly, local broker vibe
  - **Formal** — professional, highlights brokerage capabilities
  - **Cost-effective** — attacks the premium increase with numbers
  - **Risk-averse** — highlights coastal risks, positions as advisor

Copy whichever style fits your approach.

---

## Status Bar

The thin bar under the header shows real-time system health:

- **Green dot** = service is healthy
- **Yellow dot** = degraded
- **Red dot** = down
- **Red banner** = can't reach the API at all

You'll see status for: API, Database, Hunter, AI Analyzer — with
details like "Idle, no pending regions" or "Disabled (no API key)".

---

## Event Stream (for debugging)

Click **Event Stream** in the top-right header to see a live log of
everything happening in the system:

- HTTP requests (blue)
- Database operations (yellow)
- Hunter activity (green)
- AI analysis (pink)
- System events (cyan)

Use the filter buttons to focus on one type. Hit **Pause** to freeze
the stream. Hit **Clear** to start fresh.

---

## Tips

- You can draw multiple regions — the hunter processes them one at a time
- The hunter polls every 30 seconds for new regions
- If you don't see leads appearing, check the status bar for errors
- The AI analysis only runs when you click Hunt on a lead
- No AI analysis happens without documents uploaded for that property
