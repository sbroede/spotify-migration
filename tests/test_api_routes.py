from __future__ import annotations

import unittest

from spotify_migration.destination import migrate_content
from spotify_migration.source import (
    AccountSnapshot,
    FollowedArtist,
    OwnedPlaylist,
    _fetch_playlist_tracks,
)
from spotify_migration.utils import (
    FailureLog,
    follow_artists,
    follow_playlist,
    saved_albums_add,
    saved_albums_delete,
    saved_tracks_add,
    saved_tracks_delete,
    unfollow_artists,
    unfollow_playlist,
)


def empty_snapshot(*, owned_playlists: list[OwnedPlaylist] | None = None) -> AccountSnapshot:
    return AccountSnapshot(
        me={"id": "user"},
        owned_playlists=owned_playlists or [],
        followed_playlists=[],
        liked_tracks=[],
        followed_artists=[],
        saved_albums=[],
    )


class RecordingSpotify:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def _put(self, route: str, **params):
        self.calls.append(("PUT", route, params))
        return None

    def _delete(self, route: str, **params):
        self.calls.append(("DELETE", route, params))
        return None

    def current_user_playlist_create(self, name: str, **params):
        self.calls.append(("CREATE_PLAYLIST", name, params))
        return {"id": "new-playlist"}


class LibraryRouteTests(unittest.TestCase):
    def test_all_library_operations_use_generic_route_and_spotify_uris(self) -> None:
        sp = RecordingSpotify()

        saved_tracks_add(sp, ["track-id"])
        saved_tracks_delete(sp, ["spotify:track:track-id"])
        saved_albums_add(sp, ["album-id"])
        saved_albums_delete(sp, ["spotify:album:album-id"])
        follow_artists(sp, ["artist-id"])
        unfollow_artists(sp, ["spotify:artist:artist-id"])
        follow_playlist(sp, "playlist-id")
        unfollow_playlist(sp, "spotify:playlist:playlist-id")

        self.assertEqual(
            sp.calls,
            [
                ("PUT", "me/library", {"uris": "spotify:track:track-id"}),
                ("DELETE", "me/library", {"uris": "spotify:track:track-id"}),
                ("PUT", "me/library", {"uris": "spotify:album:album-id"}),
                ("DELETE", "me/library", {"uris": "spotify:album:album-id"}),
                ("PUT", "me/library", {"uris": "spotify:artist:artist-id"}),
                ("DELETE", "me/library", {"uris": "spotify:artist:artist-id"}),
                ("PUT", "me/library", {"uris": "spotify:playlist:playlist-id"}),
                ("DELETE", "me/library", {"uris": "spotify:playlist:playlist-id"}),
            ],
        )

    def test_owned_playlist_creation_uses_current_user_route(self) -> None:
        sp = RecordingSpotify()
        source = empty_snapshot(
            owned_playlists=[
                OwnedPlaylist(
                    id="source-playlist",
                    name="Example",
                    description="Description",
                    public=False,
                    collaborative=False,
                    snapshot_id="snapshot",
                )
            ]
        )

        stats = migrate_content(sp, source, empty_snapshot(), failures=FailureLog())

        self.assertEqual(stats["playlists_created"], 1)
        self.assertEqual(
            sp.calls,
            [
                (
                    "CREATE_PLAYLIST",
                    "Example",
                    {"public": False, "description": "Description"},
                )
            ],
        )

    def test_artist_writes_respect_the_library_batch_limit(self) -> None:
        sp = RecordingSpotify()
        source = empty_snapshot()
        source.followed_artists = [
            FollowedArtist(id=f"artist-{index}", name=f"Artist {index}") for index in range(41)
        ]

        stats = migrate_content(sp, source, empty_snapshot(), failures=FailureLog())

        self.assertEqual(stats["artists_followed"], 41)
        self.assertEqual([call[1] for call in sp.calls], ["me/library", "me/library"])
        self.assertEqual(
            [len(call[2]["uris"].split(",")) for call in sp.calls],
            [40, 1],
        )


class PlaylistItemsRouteTests(unittest.TestCase):
    def test_current_item_field_and_limit_are_used(self) -> None:
        class PlaylistSpotify:
            def __init__(self) -> None:
                self.params = None

            def playlist_items(self, playlist_id: str, **params):
                self.params = (playlist_id, params)
                return {
                    "items": [
                        {"item": {"uri": "spotify:track:kept", "is_local": False}},
                        {"item": {"uri": "spotify:track:local"}, "is_local": True},
                        {"item": None},
                    ],
                    "next": None,
                }

        sp = PlaylistSpotify()

        uris, skipped_local, skipped_none = _fetch_playlist_tracks(sp, "playlist-id")

        self.assertEqual(uris, ["spotify:track:kept"])
        self.assertEqual(skipped_local, 1)
        self.assertEqual(skipped_none, 1)
        self.assertEqual(sp.params[0], "playlist-id")
        self.assertEqual(sp.params[1]["limit"], 50)
        self.assertNotIn("fields", sp.params[1])


if __name__ == "__main__":
    unittest.main()
