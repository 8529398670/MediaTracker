"""What moving the database to a new key has to do beyond the record's own
encryption. Some fields are encrypted with the secret key on their own, on top
of whatever the record gets, because server.encrypt_at_rest can be off: each
has to be opened with the old key and sealed with the new one.
"""
from __future__ import annotations

from typing import Callable

from app.core import encryption
from app.core.db import Record
from app.core.db import BUCKET_USERS

# Every field encrypted with the secret key on its own, by bucket. Anything else
# that does so belongs here too, or that field is lost at the next rotation.
SEALED_FIELDS: dict[str, tuple[str, ...]] = {
    BUCKET_USERS: ("totp_secret", "totp_pending"),
}


def rekey_record(old_key: str, new_key: str) -> Callable[[str, Record], None]:
    """The rewrite db.rekey runs on every record."""

    def rewrite(bucket: str, record: Record) -> None:
        for field in SEALED_FIELDS.get(bucket, ()):
            sealed = record.get(field, "")
            if sealed:
                record[field] = encryption.xchacha_encrypt_string(new_key, encryption.xchacha_decrypt_string(old_key, sealed))

    return rewrite
