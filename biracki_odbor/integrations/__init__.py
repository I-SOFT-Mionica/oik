"""External-system integrations (Outlook etc.).

Each module here guards its dependencies behind a module-level
`*_AVAILABLE` flag so import never fails on platforms where the
underlying tooling isn't installed — the GUI code checks the flag and
hides the affordance instead of breaking app startup.
"""
