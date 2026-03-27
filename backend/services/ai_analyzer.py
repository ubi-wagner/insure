"""
AI Analyzer - The Kill & Cook Phase

On "Thumb Up", feeds Sunbiz, Audit, and I&E documents to Claude for:
1. KILL: Extract carrier, premium, expiration, decision maker
2. COOK: Generate 4 distinct outreach email styles
"""

import os
import json

import anthropic

from sqlalchemy.orm import Session

from database.models import DocType, Entity, EntityAsset

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

KILL_PROMPT = """You are an expert insurance analyst. Analyze the following three documents
for a Florida condominium association and extract the key insurance intelligence.

SUNBIZ ANNUAL REPORT:
{sunbiz}

ANNUAL FINANCIAL AUDIT:
{audit}

INCOME & EXPENSE STATEMENT:
{ie_report}

Extract and return ONLY a JSON object with these fields:
{{
  "carrier": "Primary property insurance carrier name",
  "premium": "Current annual property insurance premium (dollar amount)",
  "expiration": "Policy expiration date",
  "tiv": "Total Insured Value",
  "deductible": "Named storm deductible",
  "decision_maker": "Name of the board president or primary decision maker",
  "decision_maker_title": "Their title",
  "premium_increase_pct": "Year-over-year premium increase percentage",
  "prior_year_premium": "Previous year's premium",
  "reserve_funding_pct": "Reserve funding percentage if mentioned",
  "special_assessment": "Any special assessment amount",
  "key_risks": ["List of specific risks identified"]
}}

Return ONLY valid JSON, no markdown or explanation."""

COOK_PROMPT = """You are a skilled insurance broker crafting outreach emails to a Florida
condominium association board. Use the following intelligence to draft 4 distinct emails.

PROPERTY: {property_name}
ADDRESS: {address}
DECISION MAKER: {decision_maker} ({decision_maker_title})
CARRIER: {carrier}
CURRENT PREMIUM: {premium}
PRIOR YEAR PREMIUM: {prior_year_premium}
PREMIUM INCREASE: {premium_increase_pct}
TIV: {tiv}
EXPIRATION: {expiration}
KEY RISKS: {key_risks}

Write 4 emails, each with a Subject line and Body. Return as a JSON object:
{{
  "informal": {{
    "subject": "...",
    "body": "..."
  }},
  "formal": {{
    "subject": "...",
    "body": "..."
  }},
  "cost_effective": {{
    "subject": "...",
    "body": "..."
  }},
  "risk_averse": {{
    "subject": "...",
    "body": "..."
  }}
}}

STYLES:
1. INFORMAL: Friendly, local Florida broker vibe. First-name basis, casual but knowledgeable.
2. FORMAL: Highly professional, highlighting brokerage capabilities and market access.
3. COST-EFFECTIVE: Directly attack the premium increase. Reference specific numbers. Offer market-rate comparison.
4. RISK-AVERSE: Highlight specific coastal/wind/surge risks they may be underinsured for. Position as risk advisor.

Each email should be 150-250 words. Reference specific data points from the intelligence.
Return ONLY valid JSON, no markdown or explanation."""


def trigger_deep_dive(entity_id: int, db: Session):
    """Run the Kill & Cook analysis for a thumbed-up entity."""
    if not ANTHROPIC_API_KEY:
        print("[AI] ANTHROPIC_API_KEY not set, skipping deep dive")
        return

    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        print(f"[AI] Entity {entity_id} not found")
        return

    # Fetch all 3 document types
    assets = db.query(EntityAsset).filter(EntityAsset.entity_id == entity_id).all()
    docs = {}
    for asset in assets:
        docs[asset.doc_type.value] = asset.extracted_text or ""

    sunbiz = docs.get("SUNBIZ", "")
    audit = docs.get("AUDIT", "")
    ie_report = docs.get("IE_REPORT", "")

    if not any([sunbiz, audit, ie_report]):
        print(f"[AI] No documents found for entity {entity_id}")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # --- THE KILL ---
    print(f"[AI] Running KILL analysis for '{entity.name}'...")
    kill_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": KILL_PROMPT.format(
                    sunbiz=sunbiz,
                    audit=audit,
                    ie_report=ie_report,
                ),
            }
        ],
    )

    kill_text = kill_response.content[0].text.strip()
    try:
        intel = json.loads(kill_text)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        start = kill_text.find("{")
        end = kill_text.rfind("}") + 1
        if start >= 0 and end > start:
            intel = json.loads(kill_text[start:end])
        else:
            print(f"[AI] Failed to parse KILL response: {kill_text[:200]}")
            return

    # Save extracted intel to entity characteristics
    characteristics = entity.characteristics or {}
    characteristics.update(intel)
    entity.characteristics = characteristics
    db.commit()
    print(f"[AI] KILL complete: carrier={intel.get('carrier')}, premium={intel.get('premium')}")

    # --- THE COOK ---
    print(f"[AI] Running COOK analysis for '{entity.name}'...")
    cook_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[
            {
                "role": "user",
                "content": COOK_PROMPT.format(
                    property_name=entity.name,
                    address=entity.address or "",
                    decision_maker=intel.get("decision_maker", "Board President"),
                    decision_maker_title=intel.get("decision_maker_title", "President"),
                    carrier=intel.get("carrier", "Unknown"),
                    premium=intel.get("premium", "Unknown"),
                    prior_year_premium=intel.get("prior_year_premium", "Unknown"),
                    premium_increase_pct=intel.get("premium_increase_pct", "Unknown"),
                    tiv=intel.get("tiv", "Unknown"),
                    expiration=intel.get("expiration", "Unknown"),
                    key_risks=json.dumps(intel.get("key_risks", [])),
                ),
            }
        ],
    )

    cook_text = cook_response.content[0].text.strip()
    try:
        emails = json.loads(cook_text)
    except json.JSONDecodeError:
        start = cook_text.find("{")
        end = cook_text.rfind("}") + 1
        if start >= 0 and end > start:
            emails = json.loads(cook_text[start:end])
        else:
            print(f"[AI] Failed to parse COOK response: {cook_text[:200]}")
            return

    # Save emails to entity characteristics
    characteristics = entity.characteristics or {}
    characteristics["emails"] = emails
    entity.characteristics = characteristics
    db.commit()
    print(f"[AI] COOK complete: {len(emails)} email styles generated")
