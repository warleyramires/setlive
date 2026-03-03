from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.repertoire.models import Setlist, SetlistItem, SetlistPublicLink, Song
from apps.users.models import User


class AudienceRequestsFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="musician@example.com", password="strongpass123")
        self.song = Song.objects.create(user=self.user, title="Wonderwall", artist="Oasis")
        self.setlist = Setlist.objects.create(user=self.user, name="Bar da Sexta")
        SetlistItem.objects.create(setlist=self.setlist, song=self.song, position=1)
        self.public_link = SetlistPublicLink.objects.create(setlist=self.setlist)

        self.private_client = APIClient()
        self.private_client.force_authenticate(user=self.user)
        self.public_client = APIClient()

    def test_public_request_is_visible_in_musician_queue(self):
        public_response = self.public_client.post(
            f"/api/repertoire/public/setlists/{self.public_link.token}/requests/",
            {"song_name": "Wonderwall", "requester_name": "Ana"},
            format="json",
        )
        self.assertEqual(public_response.status_code, 201)

        queue_response = self.private_client.get(f"/api/repertoire/setlists/{self.setlist.id}/requests/")
        self.assertEqual(queue_response.status_code, 200)
        self.assertEqual(queue_response.data["count"], 1)
        self.assertEqual(queue_response.data["items"][0]["song"]["id"], self.song.id)
        self.assertEqual(queue_response.data["items"][0]["requested_song_name"], "Wonderwall")
        self.assertEqual(queue_response.data["items"][0]["requester_name"], "Ana")

    def test_short_rate_limit_blocks_immediate_second_request(self):
        first_response = self.public_client.post(
            f"/api/repertoire/public/setlists/{self.public_link.token}/requests/",
            {"song_name": "Wonderwall"},
            format="json",
        )
        self.assertEqual(first_response.status_code, 201)

        second_response = self.public_client.post(
            f"/api/repertoire/public/setlists/{self.public_link.token}/requests/",
            {"song_name": "Wonderwall"},
            format="json",
        )
        self.assertEqual(second_response.status_code, 429)


class RepertoireSecurityTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(email="a@example.com", password="strongpass123")
        self.user_b = User.objects.create_user(email="b@example.com", password="strongpass123")

        self.song_a = Song.objects.create(user=self.user_a, title="Song A", artist="Artist A")
        self.song_b = Song.objects.create(user=self.user_b, title="Song B", artist="Artist B")

        self.setlist_a = Setlist.objects.create(user=self.user_a, name="Set A")
        self.setlist_b = Setlist.objects.create(user=self.user_b, name="Set B")

        self.item_a = SetlistItem.objects.create(setlist=self.setlist_a, song=self.song_a, position=1)
        SetlistPublicLink.objects.create(setlist=self.setlist_a)

        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.user_a)

    def test_user_cannot_access_other_user_setlist(self):
        response = self.client_a.get(f"/api/repertoire/setlists/{self.setlist_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_add_other_user_song_to_setlist(self):
        response = self.client_a.post(
            f"/api/repertoire/setlists/{self.setlist_a.id}/items/",
            {"song_id": self.song_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_delete_other_user_item(self):
        item_b = SetlistItem.objects.create(setlist=self.setlist_b, song=self.song_b, position=1)
        response = self.client_a.delete(f"/api/repertoire/items/{item_b.id}/")
        self.assertEqual(response.status_code, 404)

    def test_song_list_supports_search_and_pagination(self):
        Song.objects.create(user=self.user_a, title="Another Song", artist="Artist A")
        Song.objects.create(user=self.user_a, title="Ballad", artist="Someone")

        response = self.client_a.get("/api/repertoire/songs/?search=song&page=1&page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_size"], 1)
        self.assertEqual(response.data["total"], 2)
        self.assertTrue(response.data["has_next"])
        self.assertEqual(len(response.data["items"]), 1)


class ToggleAudienceLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="musician@example.com", password="strongpass123")
        self.other_user = User.objects.create_user(email="other@example.com", password="strongpass123")
        self.setlist = Setlist.objects.create(user=self.user, name="Show de Sabado")
        self.public_link = SetlistPublicLink.objects.create(setlist=self.setlist, is_active=True)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_patch_sets_is_active_false(self):
        response = self.client.patch(
            f"/api/repertoire/setlists/{self.setlist.id}/audience-link/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.public_link.refresh_from_db()
        self.assertFalse(self.public_link.is_active)

    def test_patch_sets_is_active_true(self):
        self.public_link.is_active = False
        self.public_link.save()

        response = self.client.patch(
            f"/api/repertoire/setlists/{self.setlist.id}/audience-link/",
            {"is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_active"])
        self.public_link.refresh_from_db()
        self.assertTrue(self.public_link.is_active)

    def test_patch_by_non_owner_returns_404(self):
        other_client = APIClient()
        other_client.force_authenticate(user=self.other_user)

        response = other_client.patch(
            f"/api/repertoire/setlists/{self.setlist.id}/audience-link/",
            {"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_patch_with_non_boolean_returns_400(self):
        response = self.client.patch(
            f"/api/repertoire/setlists/{self.setlist.id}/audience-link/",
            {"is_active": "yes"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)


class PublicLinkPausedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="musician@example.com", password="strongpass123")
        self.setlist = Setlist.objects.create(user=self.user, name="Show")
        self.public_link = SetlistPublicLink.objects.create(setlist=self.setlist, is_active=False)
        self.client = APIClient()

    def test_get_public_setlist_when_paused_returns_403(self):
        response = self.client.get(f"/api/repertoire/public/setlists/{self.public_link.token}/")
        self.assertEqual(response.status_code, 403)
        self.assertIn("pausados", response.data["detail"].lower())

    def test_post_request_when_paused_returns_403(self):
        response = self.client.post(
            f"/api/repertoire/public/setlists/{self.public_link.token}/requests/",
            {"song_name": "Wonderwall"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("pausados", response.data["detail"].lower())

    def test_invalid_token_still_returns_404(self):
        response = self.client.get("/api/repertoire/public/setlists/token-inexistente/")
        self.assertEqual(response.status_code, 404)

    def test_post_invalid_token_returns_404(self):
        response = self.client.post(
            "/api/repertoire/public/setlists/token-inexistente/requests/",
            {"song_name": "Wonderwall"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
