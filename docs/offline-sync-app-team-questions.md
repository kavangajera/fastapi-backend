# Offline Sync — Questions for the App Team

We're planning to add offline support and some record-tracking fields to the API.
Before building, we need to understand three things:

## 1. What do you want?
- Offline **read-only**, or also **create / edit / delete** while offline?
- Which screens/data need to work offline — **all**, or just some (e.g. inventory, dispenses)?
- How long can a phone stay **offline** before it syncs (hours? days?)?

## 2. Why do you want it?
- What's the real situation — **poor network at the pharmacy**? Keep working during outages?
- What breaks today without it that the app team is trying to fix?

## 3. How do we sync?
- When the phone reconnects, should we send **only what changed since last sync**, or everything?
- If the same record was edited on phone and server → **who wins** (last edit, or server)?
- Records created offline need an **id the phone makes itself** (a UUID). Is the app OK generating it?
- Deletes: should a delete just **mark the row deleted** (so the phone learns it was removed) instead of actually removing it?

---