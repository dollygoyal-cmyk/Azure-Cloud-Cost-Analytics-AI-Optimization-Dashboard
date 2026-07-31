"""
Handles authentication to Azure using the App Registration (Service Principal)
created in Phase 2 of the README.
"""
import os
from azure.identity import ClientSecretCredential


def get_credential():
    """
    Returns an Azure credential object built from the .env values, or None
    if the .env file hasn't been filled in yet (so the app can fall back to
    sample data instead of crashing).
    """
    tenant_id = os.getenv("AZURE_TENANT_ID")
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")

    if not tenant_id or "your-" in tenant_id or not client_id or not client_secret:
        return None

    return ClientSecretCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def get_subscription_ids():
    """Returns the list of subscription IDs from .env, or empty list if unset."""
    raw = os.getenv("AZURE_SUBSCRIPTION_IDS", "")
    if not raw or "your-" in raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def is_configured():
    """True if real Azure credentials are available, False if running in demo mode."""
    return get_credential() is not None and len(get_subscription_ids()) > 0
