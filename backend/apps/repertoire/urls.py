from django.urls import path

from .views import (
    PublicAudienceRequestCreateView,
    PublicSetlistView,
    SetlistAddItemView,
    SetlistAudienceRequestsView,
    SetlistDetailView,
    SetlistItemDeleteView,
    SetlistListCreateView,
    SetlistPublicLinkView,
    SetlistReorderView,
    SongCifraView,
    SongDetailView,
    SongListCreateView,
)

urlpatterns = [
    path("songs/", SongListCreateView.as_view(), name="song-list-create"),
    path("songs/<int:pk>/", SongDetailView.as_view(), name="song-detail"),
    path("songs/<int:pk>/cifra/", SongCifraView.as_view(), name="song-cifra"),
    path("setlists/", SetlistListCreateView.as_view(), name="setlist-list-create"),
    path("setlists/<int:pk>/", SetlistDetailView.as_view(), name="setlist-detail"),
    path("setlists/<int:setlist_id>/items/", SetlistAddItemView.as_view(), name="setlist-add-item"),
    path("setlists/<int:setlist_id>/reorder/", SetlistReorderView.as_view(), name="setlist-reorder"),
    path("setlists/<int:setlist_id>/audience-link/", SetlistPublicLinkView.as_view(), name="setlist-audience-link"),
    path("setlists/<int:setlist_id>/requests/", SetlistAudienceRequestsView.as_view(), name="setlist-audience-requests"),
    path("items/<int:item_id>/", SetlistItemDeleteView.as_view(), name="setlist-item-delete"),
    path("public/setlists/<str:token>/", PublicSetlistView.as_view(), name="public-setlist"),
    path("public/setlists/<str:token>/requests/", PublicAudienceRequestCreateView.as_view(), name="public-request-create"),
]
