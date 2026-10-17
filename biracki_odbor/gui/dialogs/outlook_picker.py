"""Backwards-compat shim — actual dialog is `inbox_picker.py`.

The picker is backend-agnostic now (Outlook + Thunderbird both feed it
the same `InboxMessage` shape). This file kept so any in-flight code
still importing `OutlookPickerDialog` / `PickedAttachment` from here
keeps working; new code should import from `inbox_picker` /
`integrations.email_client` directly.
"""

from biracki_odbor.gui.dialogs.inbox_picker import (  # noqa: F401
    InboxPickerDialog as OutlookPickerDialog,
)
from biracki_odbor.integrations.email_client import (  # noqa: F401
    PickedAttachment,
)
