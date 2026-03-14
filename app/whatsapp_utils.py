"""WhatsApp send helpers — thin wrappers around the Meta Cloud API.

All functions require a ``phone_number_id`` (the Meta-assigned ID for the
sending phone number, stored on ``WhatsAppConnector.phone_number_id``) and a
``access_token`` (the WABA system-user token).

Addressing
----------
Meta supports two mutually-exclusive ways to address a recipient:

* ``to_number``  — E.164 phone number, e.g. ``+27821234567``.  Use this when
  the contact's phone number is available — it takes precedence.
* ``to_bsuid``   — Business-Scoped User ID (BSUID), e.g. ``ZA.13491208...``.
  Use this when the contact has enabled WhatsApp Usernames and their phone
  number was absent from the inbound webhook.  BSUIDs are carried in
  ``visitor_metadata["from_user_id"]``.  API-level send support for BSUIDs
  becomes available in May 2026; the field is accepted but ignored before then.

Error codes
-----------
131062  BSUID recipients not supported for authentication templates (OTP).
        WizzardChat does not currently send auth templates, so this code
        should not appear.  If it does, fall back to a plain text message.

References
----------
https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids/
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

_log = logging.getLogger(__name__)

# Graph API base URL.  v21.0 is the current stable version (v18.0 deprecated Sep 2024).
_META_BASE = "https://graph.facebook.com/v21.0"


def _build_recipient(to_number: str, to_bsuid: str) -> Dict[str, str]:
    """Return the addressing field(s) for a send-message payload.

    Rules:
    - If ``to_number`` is non-empty, use it (phone number takes precedence).
    - Otherwise fall back to ``to_bsuid``.
    - At least one must be non-empty; callers are responsible for validation.
    """
    if to_number:
        return {"to": to_number}
    return {"recipient": to_bsuid}


async def send_whatsapp_text(
    phone_number_id: str,
    access_token: str,
    to_number: str = "",
    to_bsuid: str = "",
    body: str = "",
) -> str:
    """Send a plain-text WhatsApp message.

    Parameters
    ----------
    phone_number_id:
        The Meta phone-number ID for the sending WhatsApp number.
    access_token:
        WABA system-user bearer token.
    to_number:
        Recipient E.164 phone number.  Use this when available.
    to_bsuid:
        Recipient BSUID.  Used as a fallback when ``to_number`` is absent.
    body:
        The plain-text message content.

    Returns
    -------
    str
        The ``wamid`` (WhatsApp message ID) returned by the API.

    Raises
    ------
    ValueError
        If neither ``to_number`` nor ``to_bsuid`` is provided.
    httpx.HTTPStatusError
        If the Meta API returns a non-2xx response.
    """
    if not to_number and not to_bsuid:
        raise ValueError("Either to_number or to_bsuid must be provided")

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "type": "text",
        "text": {"body": body, "preview_url": False},
        **_build_recipient(to_number, to_bsuid),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_META_BASE}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    wamid: str = data["messages"][0]["id"]
    _log.debug("send_whatsapp_text wamid=%s to=%s bsuid=%s", wamid, to_number, to_bsuid)
    return wamid


async def send_whatsapp_template(
    phone_number_id: str,
    access_token: str,
    to_number: str = "",
    to_bsuid: str = "",
    template_name: str = "",
    language_code: str = "en_US",
    components: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Send a pre-approved WhatsApp message template.

    Parameters
    ----------
    phone_number_id:
        The Meta phone-number ID for the sending WhatsApp number.
    access_token:
        WABA system-user bearer token.
    to_number:
        Recipient E.164 phone number.  Use this when available.
    to_bsuid:
        Recipient BSUID.  Used as a fallback when ``to_number`` is absent.
    template_name:
        The approved template name in your WABA, e.g. ``order_confirmation``.
    language_code:
        BCP-47 language tag, e.g. ``en_US`` or ``af``.
    components:
        Optional list of template component objects (header, body, buttons)
        in the Meta API format.

    Returns
    -------
    str
        The ``wamid`` returned by the API.

    Raises
    ------
    ValueError
        If neither ``to_number`` nor ``to_bsuid`` is provided, or if
        ``template_name`` is empty.
    httpx.HTTPStatusError
        If the Meta API returns a non-2xx response.
    """
    if not to_number and not to_bsuid:
        raise ValueError("Either to_number or to_bsuid must be provided")
    if not template_name:
        raise ValueError("template_name must be provided")

    payload: Dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
        },
        **_build_recipient(to_number, to_bsuid),
    }
    if components:
        payload["template"]["components"] = components

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_META_BASE}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    wamid: str = data["messages"][0]["id"]
    _log.debug(
        "send_whatsapp_template wamid=%s template=%s to=%s bsuid=%s",
        wamid, template_name, to_number, to_bsuid,
    )
    return wamid
