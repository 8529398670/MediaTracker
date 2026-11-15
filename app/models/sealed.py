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

# Every field sealed on its own, by bucket, with the purpose whose subkey of
# secret.key seals it (see encryption.subkey). Anything else that seals a field
# belongs here too, or that field is lost at the next rotation.
SEALED_FIELDS: dict[str, dict[str, str]] = {
    BUCKET_USERS: {"totp_secret": encryption.PURPOSE_TOTP, "totp_pending": encryption.PURPOSE_TOTP},
}


def rekey_record(old_key: str, new_key: str) -> Callable[[str, Record], None]:
    """The rewrite db.rekey runs on every record. A field sealed the old way,
    with secret.key itself, opens with that: this is also how an old database
    is brought up to date (db.open_store)."""

    def rewrite(bucket: str, record: Record) -> None:
        for field, purpose in SEALED_FIELDS.get(bucket, {}).items():
            sealed = record.get(field, "")
            if not sealed:
                continue
            try:
                secret = encryption.xchacha_decrypt_string(encryption.subkey(old_key, purpose), sealed)
            except encryption.CipherTextError:
                secret = encryption.xchacha_decrypt_string(old_key, sealed)
            record[field] = encryption.xchacha_encrypt_string(encryption.subkey(new_key, purpose), secret)

    return rewrite
