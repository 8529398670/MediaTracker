"""Every admin action says who did it (portal contract v3, item 6): the
account, and when it was a key, which key -- what the service account exists
for. The Logs screen shows it, and webhooks carry it."""
from __future__ import annotations


from app.core import logs
from app.models import portal
from app.tests.route_support import RoutesTestCase


class ActorAuditTest(RoutesTestCase):
    def entries(self, message: str) -> list[dict]:
        logger = self.app.state.logs
        # The writer thread is not running in a test app: write what is queued.
        while not logger._queue.empty():
            logger._write(logger._queue.get_nowait())
        logger.flush()
        return [record for record in logger.read_day(logger.today(), logs.Query())[0] if record.get("msg") == message]

    def test_a_session_names_the_account_and_no_key(self) -> None:
        status, reply = self.call("POST", f"/api/admin/users/{self.user.id}/disabled", cookie=self.owner_cookie, body={"csrf_token": self.csrf(self.owner_cookie), "disabled": True})
        self.assertEqual(status, 200, reply)
        [entry] = self.entries("user disabled set")
        self.assertEqual((entry["detail"]["actor_user_id"], entry["detail"]["actor_name"]), (self.owner.id, "Owner"))
        self.assertNotIn("actor_key_id", entry["detail"])

    def test_a_key_names_itself(self) -> None:
        self.set_config(api_keys_enabled=True)
        credential, key, account = portal.connect_portal(self.store, self.owner.id, portal.DEFAULT_PORTAL_NAME, 24 * 3600)
        status, reply = self.call("POST", "/api/admin/users", key=credential, body={"display_name": "Cy", "role": "user"})
        self.assertEqual(status, 201, reply)
        fields = {"actor_user_id": account.id, "actor_name": "ProjectPortal", "actor_key_id": key.id, "actor_key_name": key.name}
        [entry] = self.entries("user created")
        self.assertEqual({name: entry["detail"].get(name) for name in fields}, fields)
        self.assertEqual(entry["actor"]["key_name"], key.name)
