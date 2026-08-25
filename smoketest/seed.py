"""Seed a minimal but complete fixture set into the Dockerised MySQL."""
import asyncio, sys, os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from core.async_db import AsyncSessionLocal, async_engine
from core.enums import Feature, UserRole
from core.security_schemes import create_access_token
from models import Plan, Subscription
from models.user import User
from models.pharmacy import Pharmacy


async def main():
    # Wipe anything from a previous run so the smoke test is repeatable.
    async with async_engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in ["dispenses", "medicines", "drug_reports", "invoice_line_items",
                  "invoice_summaries", "invoices", "medicine_inventory", "documents",
                  "audit_dismissals", "activity_log", "subscriptions", "plans",
                  "medical_store", "user", "refill_dismissals", "record_counter"]:
            await conn.execute(text(f"TRUNCATE TABLE {t}"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

    async with AsyncSessionLocal() as db:
        owner = User(username="owner", email="owner@test.local", contact_number="5550100",
                     password_hash="x", role=UserRole.PHARMACY_OWNER.value)
        tech = User(username="tech", email="tech@test.local", contact_number="5550101",
                    password_hash="x", role=UserRole.TECHNICIAN.value)
        db.add_all([owner, tech])
        await db.flush()

        store = Pharmacy(name="Test Pharmacy", address="1 Test St", user_id=owner.user_id)
        db.add(store)
        await db.flush()

        tech.medical_store_id = store.medical_store_id

        plan = Plan(code="ULTIMATE", name="Ultimate", tier=4, monthly_price_cents=0,
                    features=[f.value for f in Feature], limits={})
        db.add(plan)
        await db.flush()

        db.add(Subscription(medical_store_id=store.medical_store_id,
                            plan_id=plan.plan_id, status="ACTIVE",
                            current_period_end=datetime.utcnow() + timedelta(days=365)))
        await db.commit()

        print(f"OWNER_TOKEN={create_access_token({'user_id': owner.user_id})}")
        print(f"TECH_TOKEN={create_access_token({'user_id': tech.user_id})}")
        print(f"STORE_ID={store.medical_store_id}")
        print(f"OWNER_ID={owner.user_id}")

asyncio.run(main())
