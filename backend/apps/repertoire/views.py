import logging
import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Max
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .cifra_scraper import fetch_cifra_text
from .models import AudienceRequest, CifraCache, Setlist, SetlistItem, SetlistPublicLink, Song

logger = logging.getLogger(__name__)

CIFRA_CACHE_DAYS = 30
from .serializers import (
    AddSetlistItemSerializer,
    AudienceRequestSerializer,
    PublicAudienceRequestCreateSerializer,
    PublicSetlistSerializer,
    ReorderSetlistSerializer,
    SetlistDetailSerializer,
    SetlistSerializer,
    SongSerializer,
)

SHORT_RATE_WINDOW_SECONDS = 15
LONG_RATE_WINDOW_SECONDS = 10 * 60
LONG_RATE_MAX_REQUESTS = 20


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _ensure_session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key or ""


def _public_url_for_token(request, token):
    if settings.FRONTEND_PUBLIC_URL:
        return f"{settings.FRONTEND_PUBLIC_URL}/public/{token}"
    return request.build_absolute_uri(f"/public/{token}")


def _queue_etag(setlist_id, count, latest_id, latest_created_at):
    latest_part = latest_created_at.isoformat() if latest_created_at else "none"
    latest_id_part = latest_id or 0
    return f'W/"setlist-{setlist_id}-count-{count}-latest-{latest_id_part}-{latest_part}"'


class SongListCreateView(generics.ListCreateAPIView):
    serializer_class = SongSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Song.objects.filter(user=self.request.user)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(title__icontains=search) | Q(artist__icontains=search))
        return queryset.order_by("title", "id")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        try:
            page = max(int(request.query_params.get("page", 1) or 1), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size_raw = int(request.query_params.get("page_size", 30) or 30)
        except (TypeError, ValueError):
            page_size_raw = 30
        page_size = min(max(page_size_raw, 1), 100)

        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)
        items = self.get_serializer(page_obj.object_list, many=True).data
        return Response(
            {
                "items": items,
                "page": page_obj.number,
                "page_size": page_size,
                "total": paginator.count,
                "has_previous": page_obj.has_previous(),
                "has_next": page_obj.has_next(),
            }
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SongDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SongSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Song.objects.filter(user=self.request.user)


class SetlistListCreateView(generics.ListCreateAPIView):
    serializer_class = SetlistSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Setlist.objects.filter(user=self.request.user).order_by("-updated_at", "-id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SetlistDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Setlist.objects.filter(user=self.request.user).prefetch_related("items__song")

    def get_serializer_class(self):
        if self.request.method == "GET":
            return SetlistDetailSerializer
        return SetlistSerializer


class SetlistAddItemView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, setlist_id):
        setlist = Setlist.objects.filter(user=request.user, id=setlist_id).first()
        if not setlist:
            return Response({"detail": "Repertorio nao encontrado."}, status=status.HTTP_404_NOT_FOUND)

        serializer = AddSetlistItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        song_id = serializer.validated_data["song_id"]

        song = Song.objects.filter(id=song_id, user=request.user).first()
        if not song:
            return Response({"detail": "Musica nao encontrada."}, status=status.HTTP_404_NOT_FOUND)

        if SetlistItem.objects.filter(setlist=setlist, song=song).exists():
            return Response({"detail": "Musica ja adicionada no repertorio."}, status=status.HTTP_400_BAD_REQUEST)

        last_position = SetlistItem.objects.filter(setlist=setlist).aggregate(max_pos=Max("position"))["max_pos"] or 0
        item = SetlistItem.objects.create(setlist=setlist, song=song, position=last_position + 1)
        setlist.save(update_fields=["updated_at"])

        return Response(
            {
                "id": item.id,
                "position": item.position,
                "song": SongSerializer(song).data,
            },
            status=status.HTTP_201_CREATED,
        )


class SetlistReorderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, setlist_id):
        setlist = Setlist.objects.filter(user=request.user, id=setlist_id).first()
        if not setlist:
            return Response({"detail": "Repertorio nao encontrado."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ReorderSetlistSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        item_ids = serializer.validated_data["item_ids"]
        items = list(SetlistItem.objects.filter(setlist=setlist).order_by("position", "id"))

        if len(item_ids) != len(items):
            return Response({"detail": "Quantidade de itens invalida para reordenar."}, status=status.HTTP_400_BAD_REQUEST)

        existing_ids = {item.id for item in items}
        provided_ids = set(item_ids)

        if existing_ids != provided_ids:
            return Response({"detail": "Lista de itens invalida."}, status=status.HTTP_400_BAD_REQUEST)

        item_map = {item.id: item for item in items}
        with transaction.atomic():
            offset = len(items) + 1000
            for temp_index, item_id in enumerate(item_ids, start=1):
                item = item_map[item_id]
                item.position = offset + temp_index
                item.save(update_fields=["position"])

            for position, item_id in enumerate(item_ids, start=1):
                item = item_map[item_id]
                item.position = position
                item.save(update_fields=["position"])
            setlist.save(update_fields=["updated_at"])

        setlist.refresh_from_db()
        return Response(SetlistDetailSerializer(setlist).data)


class SetlistItemDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, item_id):
        item = SetlistItem.objects.filter(id=item_id, setlist__user=request.user).select_related("setlist").first()
        if not item:
            return Response({"detail": "Item nao encontrado."}, status=status.HTTP_404_NOT_FOUND)

        setlist = item.setlist
        removed_position = item.position

        with transaction.atomic():
            item.delete()
            remaining = SetlistItem.objects.filter(setlist=setlist, position__gt=removed_position).order_by("position", "id")
            for next_item in remaining:
                next_item.position -= 1
                next_item.save(update_fields=["position"])
            setlist.save(update_fields=["updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)


class SetlistPublicLinkView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, setlist_id):
        setlist = Setlist.objects.filter(user=request.user, id=setlist_id).first()
        if not setlist:
            return Response({"detail": "Repertorio nao encontrado."}, status=status.HTTP_404_NOT_FOUND)

        public_link, _ = SetlistPublicLink.objects.get_or_create(setlist=setlist)
        return Response(
            {
                "setlist_id": setlist.id,
                "token": public_link.token,
                "public_url": _public_url_for_token(request, public_link.token),
                "is_active": public_link.is_active,
            }
        )


class SetlistAudienceRequestsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, setlist_id):
        setlist = Setlist.objects.filter(user=request.user, id=setlist_id).first()
        if not setlist:
            return Response({"detail": "Repertorio nao encontrado."}, status=status.HTTP_404_NOT_FOUND)

        queue = AudienceRequest.objects.filter(setlist=setlist).select_related("song")
        queue_count = queue.count()
        latest = queue.values("id", "created_at").first()
        latest_id = latest["id"] if latest else None
        latest_created_at = latest["created_at"] if latest else None
        etag = _queue_etag(setlist.id, queue_count, latest_id, latest_created_at)

        if request.headers.get("If-None-Match") == etag:
            not_modified = Response(status=status.HTTP_304_NOT_MODIFIED)
            not_modified["ETag"] = etag
            not_modified["Cache-Control"] = "no-cache"
            return not_modified

        response = Response(
            {
                "setlist_id": setlist.id,
                "count": queue_count,
                "items": AudienceRequestSerializer(queue, many=True).data,
            }
        )
        response["ETag"] = etag
        response["Cache-Control"] = "no-cache"
        return response


class PublicSetlistView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        public_link = (
            SetlistPublicLink.objects.filter(token=token, is_active=True)
            .select_related("setlist")
            .first()
        )
        if not public_link:
            return Response({"detail": "Link publico invalido."}, status=status.HTTP_404_NOT_FOUND)

        return Response(PublicSetlistSerializer(public_link.setlist).data)


class PublicAudienceRequestCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        public_link = SetlistPublicLink.objects.filter(token=token, is_active=True).select_related("setlist").first()
        if not public_link:
            return Response({"detail": "Link publico invalido."}, status=status.HTTP_404_NOT_FOUND)

        setlist = public_link.setlist
        serializer = PublicAudienceRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        requested_song_name = serializer.validated_data["song_name"].strip()
        requester_name = serializer.validated_data.get("requester_name", "").strip()
        if not requested_song_name:
            return Response({"detail": "Nome da musica e obrigatorio."}, status=status.HTTP_400_BAD_REQUEST)

        matched_song = (
            Song.objects.filter(setlist_items__setlist=setlist, title__iexact=requested_song_name)
            .order_by("id")
            .first()
        )

        client_ip = _client_ip(request)
        session_key = _ensure_session_key(request)
        short_key = f"audience:short:{setlist.id}:{client_ip}:{session_key}"
        long_key = f"audience:long:{setlist.id}:{client_ip}:{session_key}"

        if cache.get(short_key):
            return Response(
                {"detail": f"Espere {SHORT_RATE_WINDOW_SECONDS}s antes de enviar novo pedido."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if cache.add(long_key, 1, timeout=LONG_RATE_WINDOW_SECONDS):
            request_count = 1
        else:
            try:
                request_count = cache.incr(long_key)
            except ValueError:
                cache.set(long_key, 1, timeout=LONG_RATE_WINDOW_SECONDS)
                request_count = 1

        if request_count > LONG_RATE_MAX_REQUESTS:
            return Response(
                {"detail": "Limite de pedidos excedido. Tente novamente mais tarde."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        cache.set(short_key, 1, timeout=SHORT_RATE_WINDOW_SECONDS)

        audience_request = AudienceRequest.objects.create(
            setlist=setlist,
            song=matched_song,
            requested_song_name=requested_song_name,
            requester_name=requester_name,
            ip_address=client_ip or None,
            session_key=session_key,
        )

        return Response(AudienceRequestSerializer(audience_request).data, status=status.HTTP_201_CREATED)


def _to_cifra_slug(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = text.strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text


class SongCifraView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        song = Song.objects.filter(id=pk, user=request.user).first()
        if not song:
            return Response({"detail": "Musica nao encontrada."}, status=status.HTTP_404_NOT_FOUND)

        if song.chord_url:
            url = song.chord_url
        else:
            artist_slug = _to_cifra_slug(song.artist or "desconhecido")
            title_slug = _to_cifra_slug(song.title)
            url = f"https://www.cifraclub.com.br/{artist_slug}/{title_slug}/imprimir.html"

        cutoff = timezone.now() - timedelta(days=CIFRA_CACHE_DAYS)
        cached = CifraCache.objects.filter(url=url, fetched_at__gte=cutoff).first()
        if cached:
            return Response({"url": url, "content": cached.content, "cached": True})

        try:
            content = fetch_cifra_text(url)
        except Exception:
            logger.exception("Failed to fetch cifra from %s", url)
            return Response(
                {"detail": "Falha ao buscar cifra no site externo."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not content.strip():
            return Response({"detail": "Cifra nao encontrada na pagina."}, status=status.HTTP_404_NOT_FOUND)

        CifraCache.objects.update_or_create(url=url, defaults={"content": content})
        return Response({"url": url, "content": content, "cached": False})
