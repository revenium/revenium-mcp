"""The notification email update_email saves, kept beside the configuration cache with no expiry."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

SAVED_EMAIL_FILE = ".revenium_notification_email"


class SavedNotificationEmail:
    """One address in a small JSON file that stays until it is replaced or deleted."""

    def __init__(self, path: str = SAVED_EMAIL_FILE):
        self.path = Path(path)

    def read(self) -> Optional[str]:
        try:
            record = json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            logger.warning(f"Ignoring the unreadable saved notification email file {self.path}: {e}")
            return None
        email = record.get("email") if isinstance(record, dict) else None
        return email if isinstance(email, str) else None

    def save(self, email: str) -> None:
        """Replace the saved address; raises OSError, keeping the previous one, when the file cannot be written."""
        record = {"email": email, "saved_at": datetime.now(timezone.utc).isoformat()}
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=f"{self.path.name}.")
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(record, handle)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


saved_notification_email = SavedNotificationEmail()
