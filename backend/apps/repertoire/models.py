import secrets

from django.conf import settings
from django.db import models


class Song(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="songs")
    title = models.CharField(max_length=255)
    artist = models.CharField(max_length=255, blank=True)
    chord_url = models.URLField(blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    spotify_track_id = models.CharField(max_length=64, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title", "id"]

    def __str__(self):
        return f"{self.title} - {self.artist}" if self.artist else self.title


class Setlist(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="setlists")
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return self.name


def _generate_public_token():
    return secrets.token_urlsafe(18)


class SetlistPublicLink(models.Model):
    setlist = models.OneToOneField(Setlist, on_delete=models.CASCADE, related_name="public_link")
    token = models.CharField(max_length=64, unique=True, db_index=True, default=_generate_public_token)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"Publico: {self.setlist.name}"


class SetlistItem(models.Model):
    setlist = models.ForeignKey(Setlist, on_delete=models.CASCADE, related_name="items")
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="setlist_items")
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["setlist", "position"], name="uniq_setlist_position"),
        ]

    def __str__(self):
        return f"{self.setlist.name} #{self.position} - {self.song.title}"


class CifraCache(models.Model):
    url = models.URLField(unique=True)
    content = models.TextField()
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-fetched_at"]

    def __str__(self):
        return self.url


class AudienceRequest(models.Model):
    setlist = models.ForeignKey(Setlist, on_delete=models.CASCADE, related_name="audience_requests")
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="audience_requests", null=True, blank=True)
    requested_song_name = models.CharField(max_length=255, blank=True)
    requester_name = models.CharField(max_length=80, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    session_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        song_label = self.song.title if self.song else self.requested_song_name
        return f"Pedido: {song_label} ({self.setlist.name})"
