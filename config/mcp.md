# Media Tracker MCP tools

This file is generated: do not edit it. Change the tools next to their handlers and run `scripts/api_docs.sh`. Every route is in [api.md](api.md).

Every tool POST /mcp offers. Written by scripts/api_docs.sh from the registered tools; do not edit by hand. A key sees the tools its role allows (adminOnly ones need an admin key), and a tool whose feature is switched off answers like one that does not exist. route is the HTTP route the tool stands for, with the same rules; http_only are the routes a key may call that have no tool, and why.

|  |  |
|---|---|
| Endpoint | `POST /mcp` |
| Transport | Streamable HTTP, stateless: one JSON-RPC message per POST, a JSON reply |
| Auth | Authorization: Bearer <API key> |

| Tool | Route | Who | What |
|---|---|---|---|
| [`add_suggestions`](#add_suggestions) | [`POST /api/suggestions/{list_id}/add`](api.md#post-apisuggestionslist_idadd) | any key | Add suggestions |
| [`add_title`](#add_title) | [`POST /api/titles`](api.md#post-apititles) | any key | Add a title |
| [`add_to_playlist`](#add_to_playlist) | [`POST /api/playlists/{playlist_id}/add`](api.md#post-apiplaylistsplaylist_idadd) | any key | Add to a playlist |
| [`admin_cancel_login_link`](#admin_cancel_login_link) | [`POST /api/admin/users/{user_id}/cancel-login-link`](api.md#post-apiadminusersuser_idcancel-login-link) | admin keys | Stop an account's login link working (admin) |
| [`admin_cancel_login_link_bulk`](#admin_cancel_login_link_bulk) | [`POST /api/bulk/admin/users/cancel-login-link`](api.md#post-apibulkadminuserscancel-login-link) | admin keys | Stop an account's login link working, for many at once (admin) |
| [`admin_create_invite_link`](#admin_create_invite_link) | [`POST /api/admin/invite-links`](api.md#post-apiadmininvite-links) | admin keys | Create an invite link (admin) |
| [`admin_create_user`](#admin_create_user) | [`POST /api/admin/users`](api.md#post-apiadminusers) | admin keys | Create an account (admin) |
| [`admin_delete_invite_link`](#admin_delete_invite_link) | [`POST /api/admin/invite-links/{link_id}/delete`](api.md#post-apiadmininvite-linkslink_iddelete) | admin keys | Delete an invite link (admin) |
| [`admin_delete_invite_link_bulk`](#admin_delete_invite_link_bulk) | [`POST /api/bulk/admin/invite-links/delete`](api.md#post-apibulkadmininvite-linksdelete) | admin keys | Delete an invite link, for many at once (admin) |
| [`admin_delete_user`](#admin_delete_user) | [`POST /api/admin/users/{user_id}/delete`](api.md#post-apiadminusersuser_iddelete) | admin keys | Delete an account (admin) |
| [`admin_delete_user_bulk`](#admin_delete_user_bulk) | [`POST /api/bulk/admin/users/delete`](api.md#post-apibulkadminusersdelete) | admin keys | Delete an account, for many at once (admin) |
| [`admin_get_theme_defaults`](#admin_get_theme_defaults) | [`GET /api/admin/theme-defaults`](api.md#get-apiadmintheme-defaults) | admin keys | Default themes (admin) |
| [`admin_list_invite_links`](#admin_list_invite_links) | [`GET /api/admin/invite-links`](api.md#get-apiadmininvite-links) | admin keys | List invite links (admin) |
| [`admin_list_user_sessions`](#admin_list_user_sessions) | [`GET /api/admin/users/{user_id}/sessions`](api.md#get-apiadminusersuser_idsessions) | admin keys | An account's signed-in devices (admin) |
| [`admin_list_users`](#admin_list_users) | [`GET /api/admin/users`](api.md#get-apiadminusers) | admin keys | List users (admin) |
| [`admin_reissue_login`](#admin_reissue_login) | [`POST /api/admin/users/{user_id}/reissue-login`](api.md#post-apiadminusersuser_idreissue-login) | admin keys | A new login link for an account (admin) |
| [`admin_rename_invite_link`](#admin_rename_invite_link) | [`POST /api/admin/invite-links/{link_id}/rename`](api.md#post-apiadmininvite-linkslink_idrename) | admin keys | Rename an invite link (admin) |
| [`admin_rename_user`](#admin_rename_user) | [`POST /api/admin/users/{user_id}/rename`](api.md#post-apiadminusersuser_idrename) | admin keys | Rename someone (admin) |
| [`admin_reset_two_factor`](#admin_reset_two_factor) | [`POST /api/admin/users/{user_id}/reset-two-factor`](api.md#post-apiadminusersuser_idreset-two-factor) | admin keys | Turn off an account's two-factor (admin) |
| [`admin_reset_two_factor_bulk`](#admin_reset_two_factor_bulk) | [`POST /api/bulk/admin/users/reset-two-factor`](api.md#post-apibulkadminusersreset-two-factor) | admin keys | Turn off an account's two-factor, for many at once (admin) |
| [`admin_restore_invite_link`](#admin_restore_invite_link) | [`POST /api/admin/invite-links/{link_id}/restore`](api.md#post-apiadmininvite-linkslink_idrestore) | admin keys | Undo deleting an invite link (admin) |
| [`admin_restore_invite_link_bulk`](#admin_restore_invite_link_bulk) | [`POST /api/bulk/admin/invite-links/restore`](api.md#post-apibulkadmininvite-linksrestore) | admin keys | Undo deleting an invite link, for many at once (admin) |
| [`admin_revoke_access`](#admin_revoke_access) | [`POST /api/admin/users/{user_id}/revoke-access`](api.md#post-apiadminusersuser_idrevoke-access) | admin keys | Revoke a user's access (admin) |
| [`admin_revoke_access_bulk`](#admin_revoke_access_bulk) | [`POST /api/bulk/admin/users/revoke-access`](api.md#post-apibulkadminusersrevoke-access) | admin keys | Revoke a user's access, for many at once (admin) |
| [`admin_revoke_invite_link`](#admin_revoke_invite_link) | [`POST /api/admin/invite-links/{link_id}/revoke`](api.md#post-apiadmininvite-linkslink_idrevoke) | admin keys | Switch off an invite link (admin) |
| [`admin_revoke_invite_link_bulk`](#admin_revoke_invite_link_bulk) | [`POST /api/bulk/admin/invite-links/revoke`](api.md#post-apibulkadmininvite-linksrevoke) | admin keys | Switch off an invite link, for many at once (admin) |
| [`admin_revoke_user_session`](#admin_revoke_user_session) | [`POST /api/admin/users/{user_id}/sessions/{session_id}/revoke`](api.md#post-apiadminusersuser_idsessionssession_idrevoke) | admin keys | Sign out one of an account's devices (admin) |
| [`admin_revoke_user_session_bulk`](#admin_revoke_user_session_bulk) | [`POST /api/bulk/admin/users/sessions/revoke`](api.md#post-apibulkadminuserssessionsrevoke) | admin keys | Sign out one of an account's devices, for many at once (admin) |
| [`admin_set_invite_link_limits`](#admin_set_invite_link_limits) | [`POST /api/admin/invite-links/{link_id}/limits`](api.md#post-apiadmininvite-linkslink_idlimits) | admin keys | Change an invite link's places and expiry (admin) |
| [`admin_set_theme_defaults`](#admin_set_theme_defaults) | [`POST /api/admin/theme-defaults`](api.md#post-apiadmintheme-defaults) | admin keys | Replace the default themes (admin) |
| [`admin_set_user_disabled`](#admin_set_user_disabled) | [`POST /api/admin/users/{user_id}/disabled`](api.md#post-apiadminusersuser_iddisabled) | admin keys | Disable or enable a user (admin) |
| [`admin_set_user_disabled_bulk`](#admin_set_user_disabled_bulk) | [`POST /api/bulk/admin/users/disabled`](api.md#post-apibulkadminusersdisabled) | admin keys | Disable or enable a user, for many at once (admin) |
| [`admin_set_user_expiry`](#admin_set_user_expiry) | [`POST /api/admin/users/{user_id}/expiry`](api.md#post-apiadminusersuser_idexpiry) | admin keys | Set when an account expires (admin) |
| [`admin_set_user_role`](#admin_set_user_role) | [`POST /api/admin/users/{user_id}/role`](api.md#post-apiadminusersuser_idrole) | admin keys | Change an account's role (admin) |
| [`admin_set_user_role_bulk`](#admin_set_user_role_bulk) | [`POST /api/bulk/admin/users/role`](api.md#post-apibulkadminusersrole) | admin keys | Change an account's role, for many at once (admin) |
| [`admin_start_job`](#admin_start_job) | [`POST /api/jobs/{name}/start`](api.md#post-apijobsnamestart) | admin keys | Start a job (admin) |
| [`admin_stop_job`](#admin_stop_job) | [`POST /api/jobs/{name}/stop`](api.md#post-apijobsnamestop) | admin keys | Stop a job (admin) |
| [`admin_switch_on_invite_link`](#admin_switch_on_invite_link) | [`POST /api/admin/invite-links/{link_id}/switch-on`](api.md#post-apiadmininvite-linkslink_idswitch-on) | admin keys | Switch an invite link back on (admin) |
| [`admin_switch_on_invite_link_bulk`](#admin_switch_on_invite_link_bulk) | [`POST /api/bulk/admin/invite-links/switch-on`](api.md#post-apibulkadmininvite-linksswitch-on) | admin keys | Switch an invite link back on, for many at once (admin) |
| [`bulk_edit_titles`](#bulk_edit_titles) | [`POST /api/titles/bulk`](api.md#post-apititlesbulk) | any key | Change many titles |
| [`cancel_my_login_link`](#cancel_my_login_link) | [`POST /api/account/login-link/cancel`](api.md#post-apiaccountlogin-linkcancel) | any key | Stop your own login link working |
| [`check_title`](#check_title) | [`POST /api/titles/check`](api.md#post-apititlescheck) | any key | Check for a duplicate |
| [`create_my_login_link`](#create_my_login_link) | [`POST /api/account/login-link`](api.md#post-apiaccountlogin-link) | any key | A login link for yourself |
| [`create_playlist`](#create_playlist) | [`POST /api/playlists`](api.md#post-apiplaylists) | any key | Create a playlist |
| [`create_source`](#create_source) | [`POST /api/sources`](api.md#post-apisources) | any key | Add a source |
| [`create_suggestion_list`](#create_suggestion_list) | [`POST /api/suggestions`](api.md#post-apisuggestions) | any key | Create a suggestion list |
| [`create_view`](#create_view) | [`POST /api/views`](api.md#post-apiviews) | any key | Save a view |
| [`delete_playlist`](#delete_playlist) | [`POST /api/playlists/{playlist_id}/delete`](api.md#post-apiplaylistsplaylist_iddelete) | any key | Delete a playlist |
| [`delete_playlist_bulk`](#delete_playlist_bulk) | [`POST /api/bulk/playlists/delete`](api.md#post-apibulkplaylistsdelete) | any key | Delete a playlist, for many at once |
| [`delete_source`](#delete_source) | [`POST /api/sources/{source_id}/delete`](api.md#post-apisourcessource_iddelete) | any key | Delete a source |
| [`delete_source_bulk`](#delete_source_bulk) | [`POST /api/bulk/sources/delete`](api.md#post-apibulksourcesdelete) | any key | Delete a source, for many at once |
| [`delete_suggestion_list`](#delete_suggestion_list) | [`POST /api/suggestions/{list_id}/delete`](api.md#post-apisuggestionslist_iddelete) | any key | Delete a suggestion list |
| [`delete_suggestion_list_bulk`](#delete_suggestion_list_bulk) | [`POST /api/bulk/suggestions/delete`](api.md#post-apibulksuggestionsdelete) | any key | Delete a suggestion list, for many at once |
| [`delete_title`](#delete_title) | [`POST /api/titles/{title_id}/delete`](api.md#post-apititlestitle_iddelete) | any key | Delete a title |
| [`delete_type`](#delete_type) | [`POST /api/types/{type_id}/delete`](api.md#post-apitypestype_iddelete) | any key | Delete a type |
| [`delete_type_bulk`](#delete_type_bulk) | [`POST /api/bulk/types/delete`](api.md#post-apibulktypesdelete) | any key | Delete a type, for many at once |
| [`delete_view`](#delete_view) | [`POST /api/views/{view_id}/delete`](api.md#post-apiviewsview_iddelete) | any key | Delete a view |
| [`delete_view_bulk`](#delete_view_bulk) | [`POST /api/bulk/views/delete`](api.md#post-apibulkviewsdelete) | any key | Delete a view, for many at once |
| [`discover_add`](#discover_add) | [`POST /api/discover/add`](api.md#post-apidiscoveradd) | any key | Add a Discover film |
| [`discover_facts`](#discover_facts) | [`GET /api/discover/facts`](api.md#get-apidiscoverfacts) | any key | Discover film details |
| [`discover_meta`](#discover_meta) | [`GET /api/discover/meta`](api.md#get-apidiscovermeta) | any key | Discover catalogue |
| [`discover_search`](#discover_search) | [`GET /api/discover`](api.md#get-apidiscover) | any key | Search Discover |
| [`dismiss_duplicates`](#dismiss_duplicates) | [`POST /api/dupes/dismiss`](api.md#post-apidupesdismiss) | any key | Not duplicates |
| [`enrich_title`](#enrich_title) | [`POST /api/titles/{title_id}/enrich`](api.md#post-apititlestitle_idenrich) | any key | Fill a title in |
| [`enrich_title_bulk`](#enrich_title_bulk) | [`POST /api/bulk/titles/enrich`](api.md#post-apibulktitlesenrich) | any key | Fill a title in, for many at once |
| [`get_prefs`](#get_prefs) | [`GET /api/prefs`](api.md#get-apiprefs) | any key | Settings |
| [`get_title`](#get_title) | [`GET /api/titles/{title_id}`](api.md#get-apititlestitle_id) | any key | Get a title |
| [`get_vocab`](#get_vocab) | [`GET /api/vocab`](api.md#get-apivocab) | any key | Library vocabulary |
| [`import_items`](#import_items) | [`POST /api/import/items`](api.md#post-apiimportitems) | any key | Import titles |
| [`import_parse`](#import_parse) | [`POST /api/import/parse`](api.md#post-apiimportparse) | any key | Read an import |
| [`jobs_status`](#jobs_status) | [`GET /api/jobs`](api.md#get-apijobs) | any key | Background jobs |
| [`label_my_session`](#label_my_session) | [`POST /api/account/sessions/{session_id}/label`](api.md#post-apiaccountsessionssession_idlabel) | any key | Name one of your devices |
| [`list_duplicates`](#list_duplicates) | [`GET /api/dupes`](api.md#get-apidupes) | any key | Possible duplicates |
| [`list_my_sessions`](#list_my_sessions) | [`GET /api/account/sessions`](api.md#get-apiaccountsessions) | any key | Your signed-in devices |
| [`list_playlists`](#list_playlists) | [`GET /api/playlists`](api.md#get-apiplaylists) | any key | Playlists |
| [`list_sources`](#list_sources) | [`GET /api/sources`](api.md#get-apisources) | any key | Sources |
| [`list_suggestions`](#list_suggestions) | [`GET /api/suggestions`](api.md#get-apisuggestions) | any key | Suggestion lists |
| [`list_team`](#list_team) | [`GET /api/team`](api.md#get-apiteam) | any key | List team |
| [`list_types`](#list_types) | [`GET /api/types`](api.md#get-apitypes) | any key | Media types |
| [`list_views`](#list_views) | [`GET /api/views`](api.md#get-apiviews) | any key | Saved views |
| [`lookup`](#lookup) | [`POST /api/resolve`](api.md#post-apiresolve) | any key | Look titles up |
| [`merge_titles`](#merge_titles) | [`POST /api/titles/{title_id}/merge`](api.md#post-apititlestitle_idmerge) | any key | Merge duplicates |
| [`merge_titles_bulk`](#merge_titles_bulk) | [`POST /api/bulk/titles/merge`](api.md#post-apibulktitlesmerge) | any key | Merge duplicates, for many at once |
| [`move_in_playlist`](#move_in_playlist) | [`POST /api/playlists/{playlist_id}/move`](api.md#post-apiplaylistsplaylist_idmove) | any key | Move within a playlist |
| [`move_suggestion`](#move_suggestion) | [`POST /api/suggestions/{list_id}/move`](api.md#post-apisuggestionslist_idmove) | any key | Move a suggestion |
| [`remove_from_playlist`](#remove_from_playlist) | [`POST /api/playlists/{playlist_id}/remove`](api.md#post-apiplaylistsplaylist_idremove) | any key | Remove from a playlist |
| [`remove_suggestions`](#remove_suggestions) | [`POST /api/suggestions/{list_id}/remove`](api.md#post-apisuggestionslist_idremove) | any key | Remove suggestions |
| [`rename_account`](#rename_account) | [`POST /api/account/rename`](api.md#post-apiaccountrename) | any key | Rename your account |
| [`rename_playlist`](#rename_playlist) | [`POST /api/playlists/{playlist_id}/update`](api.md#post-apiplaylistsplaylist_idupdate) | any key | Rename a playlist |
| [`rename_suggestion_list`](#rename_suggestion_list) | [`POST /api/suggestions/{list_id}/update`](api.md#post-apisuggestionslist_idupdate) | any key | Rename a suggestion list |
| [`reorder_playlists`](#reorder_playlists) | [`POST /api/playlists/reorder`](api.md#post-apiplaylistsreorder) | any key | Order playlists |
| [`reorder_suggestion_lists`](#reorder_suggestion_lists) | [`POST /api/suggestions/reorder`](api.md#post-apisuggestionsreorder) | any key | Order suggestion lists |
| [`reorder_views`](#reorder_views) | [`POST /api/views/reorder`](api.md#post-apiviewsreorder) | any key | Order views |
| [`restore_playlist`](#restore_playlist) | [`POST /api/playlists/{playlist_id}/restore`](api.md#post-apiplaylistsplaylist_idrestore) | any key | Restore a playlist |
| [`restore_playlist_bulk`](#restore_playlist_bulk) | [`POST /api/bulk/playlists/restore`](api.md#post-apibulkplaylistsrestore) | any key | Restore a playlist, for many at once |
| [`restore_source`](#restore_source) | [`POST /api/sources/{source_id}/restore`](api.md#post-apisourcessource_idrestore) | any key | Restore a source |
| [`restore_source_bulk`](#restore_source_bulk) | [`POST /api/bulk/sources/restore`](api.md#post-apibulksourcesrestore) | any key | Restore a source, for many at once |
| [`restore_suggestion_list`](#restore_suggestion_list) | [`POST /api/suggestions/{list_id}/restore`](api.md#post-apisuggestionslist_idrestore) | any key | Restore a suggestion list |
| [`restore_suggestion_list_bulk`](#restore_suggestion_list_bulk) | [`POST /api/bulk/suggestions/restore`](api.md#post-apibulksuggestionsrestore) | any key | Restore a suggestion list, for many at once |
| [`restore_title`](#restore_title) | [`POST /api/titles/{title_id}/restore`](api.md#post-apititlestitle_idrestore) | any key | Restore a title |
| [`restore_type`](#restore_type) | [`POST /api/types/{type_id}/restore`](api.md#post-apitypestype_idrestore) | any key | Restore a type |
| [`restore_type_bulk`](#restore_type_bulk) | [`POST /api/bulk/types/restore`](api.md#post-apibulktypesrestore) | any key | Restore a type, for many at once |
| [`restore_view`](#restore_view) | [`POST /api/views/{view_id}/restore`](api.md#post-apiviewsview_idrestore) | any key | Restore a view |
| [`restore_view_bulk`](#restore_view_bulk) | [`POST /api/bulk/views/restore`](api.md#post-apibulkviewsrestore) | any key | Restore a view, for many at once |
| [`revoke_my_other_sessions`](#revoke_my_other_sessions) | [`POST /api/account/sessions/revoke-others`](api.md#post-apiaccountsessionsrevoke-others) | any key | Sign out all your devices |
| [`revoke_my_session`](#revoke_my_session) | [`POST /api/account/sessions/{session_id}/revoke`](api.md#post-apiaccountsessionssession_idrevoke) | any key | Sign out one of your devices |
| [`revoke_my_session_bulk`](#revoke_my_session_bulk) | [`POST /api/bulk/account/sessions/revoke`](api.md#post-apibulkaccountsessionsrevoke) | any key | Sign out one of your devices, for many at once |
| [`save_prefs`](#save_prefs) | [`POST /api/prefs`](api.md#post-apiprefs) | any key | Change settings |
| [`save_type`](#save_type) | [`POST /api/types`](api.md#post-apitypes) | any key | Add or change a type |
| [`search_library`](#search_library) | [`GET /api/library/search`](api.md#get-apilibrarysearch) | any key | Search the library |
| [`set_playlist_items`](#set_playlist_items) | [`POST /api/playlists/{playlist_id}/set`](api.md#post-apiplaylistsplaylist_idset) | any key | Set a playlist's titles |
| [`set_state`](#set_state) | [`POST /api/state/{title_id}`](api.md#post-apistatetitle_id) | any key | Set status, rating or heart |
| [`set_states`](#set_states) | [`POST /api/state/bulk`](api.md#post-apistatebulk) | any key | Set state on many titles |
| [`set_suggestion_items`](#set_suggestion_items) | [`POST /api/suggestions/{list_id}/set`](api.md#post-apisuggestionslist_idset) | any key | Set a suggestion list's items |
| [`set_suggestion_note`](#set_suggestion_note) | [`POST /api/suggestions/{list_id}/note`](api.md#post-apisuggestionslist_idnote) | any key | Change a suggestion's note |
| [`set_theme`](#set_theme) | [`POST /api/account/theme`](api.md#post-apiaccounttheme) | any key | Pick your theme |
| [`set_themes`](#set_themes) | [`POST /api/account/themes`](api.md#post-apiaccountthemes) | any key | Replace your own themes |
| [`set_verdict`](#set_verdict) | [`POST /api/discover/verdict`](api.md#post-apidiscoververdict) | any key | Skip a Discover film |
| [`undismiss_duplicates`](#undismiss_duplicates) | [`POST /api/dupes/undismiss`](api.md#post-apidupesundismiss) | any key | Undo not duplicates |
| [`undo_import`](#undo_import) | [`POST /api/import/{batch_id}/undo`](api.md#post-apiimportbatch_idundo) | any key | Undo an import |
| [`undo_merge`](#undo_merge) | [`POST /api/merges/{merge_id}/undo`](api.md#post-apimergesmerge_idundo) | any key | Undo a merge |
| [`undo_merge_bulk`](#undo_merge_bulk) | [`POST /api/bulk/merges/undo`](api.md#post-apibulkmergesundo) | any key | Undo a merge, for many at once |
| [`update_source`](#update_source) | [`POST /api/sources/{source_id}/update`](api.md#post-apisourcessource_idupdate) | any key | Change a source |
| [`update_title`](#update_title) | [`POST /api/titles/{title_id}/update`](api.md#post-apititlestitle_idupdate) | any key | Edit a title |
| [`update_title_bulk`](#update_title_bulk) | [`POST /api/bulk/titles/update`](api.md#post-apibulktitlesupdate) | any key | Edit a title, for many at once |
| [`update_view`](#update_view) | [`POST /api/views/{view_id}/update`](api.md#post-apiviewsview_idupdate) | any key | Change a view |
| [`whoami`](#whoami) | [`GET /api/me`](api.md#get-apime) | any key | Who am I |

## add_suggestions

Suggest films for the person to import or watch: Discover films by key (film_keys, from discover_search) and/or library titles (title_ids, from search_library), with a one-line note saying why ("same director as Heat"). Call once per note. One already in the list keeps its place and takes the new note. Returns the items before.

|  |  |
|---|---|
| Route | [`POST /api/suggestions/{list_id}/add`](api.md#post-apisuggestionslist_idadd) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `film_keys` | array of string | no |  | Discover film keys, from GET /api/discover (discover_search over MCP). |
| `list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `note` | string | no | at most 200 characters | Why it is suggested, in a line: shown under the card. |
| `position` | integer or null | no | at least 1 | 1-based; the end by default. |
| `title_ids` | array of string | no |  | Library title ids, from GET /api/library (search_library over MCP). |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## add_title

Add a title to the family library and put it on a person's list (state.status: queue by default). Refused with 409 possible_duplicate and the dupes it resembles unless force is true. Details are filled in in the background. A possible duplicate answers created: false with possible_duplicates instead.

|  |  |
|---|---|
| Route | [`POST /api/titles`](api.md#post-apititles) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `force` | boolean | no |  | Add it even if it looks like a title the library has. |
| `state` | object | no |  | A person's state: status (queue, watching, watched, dropped, or null), rating 1-10 or null, heart, note, watched_at. |
| `title` | object | yes |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## add_to_playlist

Add titles at position (the end by default); the rest renumber. Returns the items before, which setting the items takes back.

|  |  |
|---|---|
| Route | [`POST /api/playlists/{playlist_id}/add`](api.md#post-apiplaylistsplaylist_idadd) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `position` | integer or null | no | at least 1 | 1-based; the end by default. |
| `title_ids` | array of string | yes |  | Title ids, from GET /api/library (search_library over MCP). |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## admin_cancel_login_link

Void an account's live login link without making a new one: a link that went somewhere it should not have. Devices it already signed in stay signed in; admin_revoke_access ends those too. Answers with removed: 0 or 1.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/cancel-login-link`](api.md#post-apiadminusersuser_idcancel-login-link) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_cancel_login_link_bulk

Runs admin_cancel_login_link once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/users/cancel-login-link`](api.md#post-apibulkadminuserscancel-login-link) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## admin_create_invite_link

One link for a group: each person who opens it joins as a new account with role (user, the default, or viewer), up to max_uses people, for days days. Answers with join_url (shown only now) and the link's details. Revoking or deleting this API key switches the link off.

|  |  |
|---|---|
| Route | [`POST /api/admin/invite-links`](api.md#post-apiadmininvite-links) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `days` | integer | yes | 1 to 365 |  |
| `label` | string | yes | 1 to 80 characters |  |
| `max_uses` | integer | yes | 1 to 1000 |  |
| `role` | string | no | one of `user`, `viewer`; default `user` | The role each person who joins gets: user, or viewer (reads only). |

## admin_create_user

Make a new account and its first login link, to hand to the person. role is admin, user or viewer (reads only). account_expires_at, when given, is when the account stops working. Answers with user_id and the link. Answers with login_url (open it to sign in; it works once unless max_uses says otherwise), expires_at and max_uses. Any older link the account could still use stops working; its signed-in devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs out every device it signed in.

|  |  |
|---|---|
| Route | [`POST /api/admin/users`](api.md#post-apiadminusers) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `account_expires_at` | string (date-time) or null | no |  | When the account stops working (RFC 3339). Left out: never. expires_in_minutes is the login link's expiry, not this. |
| `display_name` | string | yes | 1 to 80 characters |  |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `kind` | string | no | one of `person`, `service`; default `person` | person, the default. service is refused (403 service_account): a service account is made by Connect on the owner's API keys screen. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |

## admin_delete_invite_link

Take an invite link off the list and stop it working. The accounts it made stay. admin_restore_invite_link undoes it for a few minutes.

|  |  |
|---|---|
| Route | [`POST /api/admin/invite-links/{link_id}/delete`](api.md#post-apiadmininvite-linkslink_iddelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

## admin_delete_invite_link_bulk

Runs admin_delete_invite_link once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/invite-links/delete`](api.md#post-apibulkadmininvite-linksdelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## admin_delete_user

Remove an account for good, with its sessions, login link and API keys. Cannot be undone: admin_set_user_disabled is the reversible version. Only the owner deletes an admin; nobody deletes the owner or themselves.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/delete`](api.md#post-apiadminusersuser_iddelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_delete_user_bulk

Runs admin_delete_user once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/users/delete`](api.md#post-apibulkadminusersdelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## admin_get_theme_defaults

The theme list everyone without their own list sees. themes is null while the built-in ones apply.

|  |  |
|---|---|
| Route | [`GET /api/admin/theme-defaults`](api.md#get-apiadmintheme-defaults) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## admin_list_invite_links

Group invite links, a page at a time: label, places used and left, expiry, and whether each still works. The links themselves are never shown again after creation. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Route | [`GET /api/admin/invite-links`](api.md#get-apiadmininvite-links) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `dir` | string | no | one of `asc`, `desc` | Default asc. |
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | string | no |  | Keep links whose label or maker contains this, in any case. |
| `sort` | string | no | one of `label`, `used`, `expires_at` | Field to sort the whole list by. Rows without it go last. |

## admin_list_user_sessions

Where an account is signed in: every session, with when it started and was last seen. Addresses are shown to the owner only, and only the owner sees the owner's.

|  |  |
|---|---|
| Route | [`GET /api/admin/users/{user_id}/sessions`](api.md#get-apiadminusersuser_idsessions) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_list_users

Accounts, a page at a time, including disabled ones, with each one's role and which is the owner. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Route | [`GET /api/admin/users`](api.md#get-apiadminusers) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `dir` | string | no | one of `asc`, `desc` | Default asc. |
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | string | no |  | Keep accounts whose name or username contains this, in any case. |
| `sort` | string | no | one of `display_name`, `role`, `disabled`, `created_at` | Field to sort the whole list by. Rows without it go last. |

## admin_reissue_login

For someone who lost their device or their link: a fresh login link for their account. Answers with login_url (open it to sign in; it works once unless max_uses says otherwise), expires_at and max_uses. Any older link the account could still use stops working; its signed-in devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs out every device it signed in.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/reissue-login`](api.md#post-apiadminusersuser_idreissue-login) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_rename_invite_link

Change the label people see on an invite link's join page (1-80 characters). expect, when given, is the label you think it has now.

|  |  |
|---|---|
| Route | [`POST /api/admin/invite-links/{link_id}/rename`](api.md#post-apiadmininvite-linkslink_idrename) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | string or null | no |  | The label you think it has. Answers 409 if it has another. |
| `label` | string | yes | 1 to 80 characters | 1-80 characters. |
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

## admin_rename_user

Change another account's display name (1-80 characters). Only the owner renames an admin. expect, when given, is the name you think it has now; if it changed meanwhile the rename is refused with the current name.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/rename`](api.md#post-apiadminusersuser_idrename) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes | 1 to 80 characters | 1-80 characters. |
| `expect` | string or null | no |  | The name you think they have. Answers 409 if it is another. |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_reset_two_factor

For someone who lost both their phone and their recovery codes: switches their two-factor sign-in off so a login link lets them in again. Only the owner resets an admin's; the owner's is reset from a shell.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/reset-two-factor`](api.md#post-apiadminusersuser_idreset-two-factor) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_reset_two_factor_bulk

Runs admin_reset_two_factor once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/users/reset-two-factor`](api.md#post-apibulkadminusersreset-two-factor) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## admin_restore_invite_link

Bring back an invite link deleted in the last few minutes, working as before. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Route | [`POST /api/admin/invite-links/{link_id}/restore`](api.md#post-apiadmininvite-linkslink_idrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

## admin_restore_invite_link_bulk

Runs admin_restore_invite_link once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/invite-links/restore`](api.md#post-apibulkadmininvite-linksrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## admin_revoke_access

For an account that may be compromised: ends every session and voids its live login link and every API key it holds, at once. The account stays enabled; admin_reissue_login lets its owner back in. The owner and your own account cannot be revoked.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/revoke-access`](api.md#post-apiadminusersuser_idrevoke-access) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_revoke_access_bulk

Runs admin_revoke_access once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/users/revoke-access`](api.md#post-apibulkadminusersrevoke-access) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## admin_revoke_invite_link

Stop an invite link from letting anyone else join or sign in through it. Accounts it already made keep working. Cannot be switched back on.

|  |  |
|---|---|
| Route | [`POST /api/admin/invite-links/{link_id}/revoke`](api.md#post-apiadmininvite-linkslink_idrevoke) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

## admin_revoke_invite_link_bulk

Runs admin_revoke_invite_link once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/invite-links/revoke`](api.md#post-apibulkadmininvite-linksrevoke) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## admin_revoke_user_session

End one of an account's sessions, rather than all of them with admin_revoke_access.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/sessions/{session_id}/revoke`](api.md#post-apiadminusersuser_idsessionssession_idrevoke) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_revoke_user_session_bulk

Runs admin_revoke_user_session once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/users/sessions/revoke`](api.md#post-apibulkadminuserssessionsrevoke) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## admin_set_invite_link_limits

Set how many people the link may take in (never fewer than have joined) and, when days is given, a new expiry counted from now. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Route | [`POST /api/admin/invite-links/{link_id}/limits`](api.md#post-apiadmininvite-linkslink_idlimits) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `days` | integer or null | no | 1 to 365 | Counted from now. Leave out to keep the expiry. |
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `max_uses` | integer | yes | 1 to 1000 | Not fewer than have joined. |

## admin_set_theme_defaults

Replace the theme list everyone without their own list sees, 1 to 40 themes in the Theme schema of the API reference. null puts the built-in themes back.

|  |  |
|---|---|
| Route | [`POST /api/admin/theme-defaults`](api.md#post-apiadmintheme-defaults) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | no |  | Which built-in themes this list has seen: the highest since in Theme.builtIn (static/js/theme.js) when it was saved. Built-in themes added after that join the list the browser shows. Left out: 0, the first ones. |
| `themes` | array of object or null | no |  | 1 to 40 themes. null goes back to the built-in ones. |
| `themes[].accent` | string | yes |  | The main color: what you can press. |
| `themes[].background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].button` | object or null | no |  | How the theme's buttons look. A choice left out is the default (rounded, normal, raised, normal). |
| `themes[].button.case` | string | no | one of `normal`, `upper` |  |
| `themes[].button.depth` | string | no | one of `flat`, `raised`, `glossy` |  |
| `themes[].button.shape` | string | no | one of `square`, `soft`, `rounded`, `pill` |  |
| `themes[].button.weight` | string | no | one of `normal`, `medium`, `bold` |  |
| `themes[].dark` | object or null | no |  | A light theme's colors for dark mode, kept while it is light. Switching the theme to dark swaps them in. A light theme's light (or a dark theme's dark) is dropped. |
| `themes[].dark.accent` | string | yes |  | The main color: what you can press. |
| `themes[].dark.background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].dark.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].dark.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].dark.surface` | string | no |  | Cards. Left out: the mode's own. |
| `themes[].id` | string | yes |  | Lower-case letters, digits, - and _, up to 32. |
| `themes[].light` | object or null | no |  | A dark theme's colors for light mode, kept while it is dark. Switching the theme to light swaps them in. |
| `themes[].light.accent` | string | yes |  | The main color: what you can press. |
| `themes[].light.background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].light.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].light.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].light.surface` | string | no |  | Cards. Left out: the mode's own. |
| `themes[].mode` | string | yes | one of `light`, `dark` |  |
| `themes[].name` | string | yes |  | 1 to 60 characters. |
| `themes[].overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].surface` | string | no |  | Cards. Left out: the mode's own. |

## admin_set_user_disabled

Switch an account off (disabled: true) or back on (false). Disabling signs it out everywhere and voids its live login link; its API keys stop working while it is off. Reversible. The owner and your own account cannot be disabled.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/disabled`](api.md#post-apiadminusersuser_iddisabled) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `disabled` | boolean | yes |  |  |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_set_user_disabled_bulk

Runs admin_set_user_disabled once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/users/disabled`](api.md#post-apibulkadminusersdisabled) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].disabled` | boolean | no |  |  |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.disabled` | boolean | no |  |  |

## admin_set_user_expiry

expires_at is when the account stops working (RFC 3339), or null for never. Once it passes the account counts as disabled: sign-in, its sessions and its keys stop, and housekeeping disables it and revokes its access. A later expiry does not re-enable an account housekeeping already disabled. It must be in the future. The owner's account never expires; only the owner sets an admin's.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/expiry`](api.md#post-apiadminusersuser_idexpiry) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | When the account stops working (RFC 3339), or null for never. |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_set_user_role

Make an account an admin, an ordinary user, or a viewer, who may read but change nothing. Only the owner takes an admin's rights away; the owner is always an admin, and nobody changes their own role. Becoming an admin ends the account's sessions and live login link.

|  |  |
|---|---|
| Route | [`POST /api/admin/users/{user_id}/role`](api.md#post-apiadminusersuser_idrole) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

## admin_set_user_role_bulk

Runs admin_set_user_role once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/users/role`](api.md#post-apibulkadminusersrole) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].role` | string | no | one of `admin`, `user`, `viewer` |  |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.role` | string | no | one of `admin`, `user`, `viewer` |  |

## admin_start_job

Start a background job by its name (one marked manual). options are the job's own settings. Each job can make thousands of outbound calls.

|  |  |
|---|---|
| Route | [`POST /api/jobs/{name}/start`](api.md#post-apijobsnamestart) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  | A job's name, from GET /api/jobs. |
| `options` | object | no |  | The job's own settings. |

## admin_stop_job

Ask a running background job to stop.

|  |  |
|---|---|
| Route | [`POST /api/jobs/{name}/stop`](api.md#post-apijobsnamestop) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  | A job's name, from GET /api/jobs. |

## admin_switch_on_invite_link

Undo admin_revoke_invite_link: anyone still holding the link can use it again. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Route | [`POST /api/admin/invite-links/{link_id}/switch-on`](api.md#post-apiadmininvite-linkslink_idswitch-on) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

## admin_switch_on_invite_link_bulk

Runs admin_switch_on_invite_link once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/admin/invite-links/switch-on`](api.md#post-apibulkadmininvite-linksswitch-on) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## bulk_edit_titles

One change to many titles at once. op: set_type (value: a type id), add_tags or remove_tags (value: a list of tags), delete, restore, or set_fields (value: {title id: fields}, the undo). Returns each title's previous values; send them back with set_fields to undo. Deletes are soft and restorable.

|  |  |
|---|---|
| Route | [`POST /api/titles/bulk`](api.md#post-apititlesbulk) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ids` | array of string | yes |  | Title ids, at most 2000. |
| `op` | string | yes | one of `set_type`, `add_tags`, `remove_tags`, `delete`, `restore`, `set_fields` | The change. |
| `value` | any | no |  | set_type: a type id. add_tags, remove_tags: a list of tags. set_fields: {title id: fields}, the undo. |

## cancel_my_login_link

Void your account's live login link without making a new one. Devices it already signed in stay signed in. Answers with removed: 0 or 1.

|  |  |
|---|---|
| Route | [`POST /api/account/login-link/cancel`](api.md#post-apiaccountlogin-linkcancel) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## check_title

Would adding this title make a duplicate? The library titles it resembles, with a score. Writes nothing.

|  |  |
|---|---|
| Route | [`POST /api/titles/check`](api.md#post-apititlescheck) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `title` | object | yes |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |

## create_my_login_link

A link that signs your own account in on a browser or another device. An API key may ask only if your account let it, from a browser session (POST /api/keys/{key_id}/sign-in); its link works once, for at most 15 minutes. Only works if this key was allowed to make sign-in links, on the API keys card. Answers with login_url (open it to sign in; it works once, for at most 15 minutes), expires_at and max_uses. Any older link the account could still use stops working; its signed-in devices stay signed in. Revoking or deleting this API key voids the link while it is unused, and signs out every device it signed in.

|  |  |
|---|---|
| Route | [`POST /api/account/login-link`](api.md#post-apiaccountlogin-link) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |

## create_playlist

A new playlist, optionally with titles (items: title ids, in order).

|  |  |
|---|---|
| Route | [`POST /api/playlists`](api.md#post-apiplaylists) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of string | no |  | Title ids, in order. |
| `name` | string | yes |  | Up to 80 characters. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## create_source

Remember a list or page titles were found on.

|  |  |
|---|---|
| Route | [`POST /api/sources`](api.md#post-apisources) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `note` | string | no |  | Up to 2000 characters. |
| `tags` | array of string | no |  | Up to 20. |
| `title` | string | no |  | Up to 300 characters. |
| `url` | string | yes |  | An http(s) link. |

## create_suggestion_list

A new, empty suggestion list. Fill it with add.

|  |  |
|---|---|
| Route | [`POST /api/suggestions`](api.md#post-apisuggestions) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  | Up to 80 characters. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## create_view

Save a named view of a screen.

|  |  |
|---|---|
| Route | [`POST /api/views`](api.md#post-apiviews) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `card` | object or null | no |  | How cards look in this view. |
| `icon` | string | no |  |  |
| `name` | string | yes |  | Up to 80 characters. |
| `query` | string | no |  | The screen's address, such as #library/all/queue?runtime=..100. |
| `scope` | string | no |  | The library section it is on. |
| `screen` | string | no |  | library or discover. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## delete_playlist

Delete a playlist. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/playlists/{playlist_id}/delete`](api.md#post-apiplaylistsplaylist_iddelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## delete_playlist_bulk

Runs delete_playlist once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/playlists/delete`](api.md#post-apibulkplaylistsdelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## delete_source

Delete a source. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/sources/{source_id}/delete`](api.md#post-apisourcessource_iddelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `source_id` | string | yes |  | A source's id, from GET /api/sources. |

## delete_source_bulk

Runs delete_source once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/sources/delete`](api.md#post-apibulksourcesdelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].source_id` | string | yes |  | A source's id, from GET /api/sources. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## delete_suggestion_list

Delete a suggestion list. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/suggestions/{list_id}/delete`](api.md#post-apisuggestionslist_iddelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## delete_suggestion_list_bulk

Runs delete_suggestion_list once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/suggestions/delete`](api.md#post-apibulksuggestionsdelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## delete_title

Take a title out of the library for everyone. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/titles/{title_id}/delete`](api.md#post-apititlestitle_iddelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

## delete_type

Delete a media type. One that still holds titles needs reassign_to, the type they move to (409 type_in_use with their count otherwise). Movies and TV cannot be deleted. Soft: restoring it brings it back.

|  |  |
|---|---|
| Route | [`POST /api/types/{type_id}/delete`](api.md#post-apitypestype_iddelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `reassign_to` | string or null | no |  | The type its titles move to. Needed while it holds any. |
| `type_id` | string | yes |  | A type's id, from GET /api/types. |

## delete_type_bulk

Runs delete_type once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/types/delete`](api.md#post-apibulktypesdelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].reassign_to` | string or null | no |  | The type its titles move to. Needed while it holds any. |
| `items[].type_id` | string | yes |  | A type's id, from GET /api/types. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.reassign_to` | string or null | no |  | The type its titles move to. Needed while it holds any. |

## delete_view

Delete a saved view. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/views/{view_id}/delete`](api.md#post-apiviewsview_iddelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `view_id` | integer | yes | at least 1 | A view's id, from GET /api/views. |

## delete_view_bulk

Runs delete_view once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/views/delete`](api.md#post-apibulkviewsdelete) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `items[].view_id` | integer | yes | at least 1 | A view's id, from GET /api/views. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## discover_add

Add a film from Discover (the film object as it was given) to the library, with its Wikipedia details. status: watched for Seen it, or leave it out for no list. Refused with 409 possible_duplicate and the dupes unless force is true. A possible duplicate answers created: false with possible_duplicates instead.

|  |  |
|---|---|
| Route | [`POST /api/discover/add`](api.md#post-apidiscoveradd) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `film` | object | yes |  | A film as GET /api/discover gives it. |
| `force` | boolean | no |  | Add it even if it looks like a title the library has. |
| `status` | string or null | no |  | watched for Seen it; leave out for no list. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## discover_facts

Plot, cast and poster for up to 60 catalogue films, by article name (a film's url ends in it), keyed by article.

|  |  |
|---|---|
| Route | [`GET /api/discover/facts`](api.md#get-apidiscoverfacts) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `articles` | string | no |  | Wikipedia article names (a film's article), separated by \|. At most 60. |

## discover_meta

What the Discover catalogue holds: its source lists and topics, coverage, and rating counts.

|  |  |
|---|---|
| Route | [`GET /api/discover/meta`](api.md#get-apidiscovermeta) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## discover_search

The Wikipedia film catalogue, minus films the person skipped or watched unless asked for. Each film says whether it is already in the library (title_id) and the person's status on it. Answers total, films and, when nothing matched the exact words, fuzzy: true. q may be an IMDb title link or tt id, which finds that film whatever the other filters say. With q, title_hit says whether any catalogue film, filters aside, has those words in its title. Words the filters leave nothing for are searched again with the filters set aside: unfiltered: true.

|  |  |
|---|---|
| Route | [`GET /api/discover`](api.md#get-apidiscover) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `actor` | string | no |  | A cast member's name. |
| `from` | string | no |  | Earliest year. |
| `genre` | string | no |  | Genres, comma-separated. |
| `genremode` | string | no |  | all: every genre given. Default any. |
| `imdbfrom` | string | no |  | Lowest IMDb score, 0-10. |
| `imdbto` | string | no |  | Highest IMDb score, 0-10. |
| `library` | string | no |  | hide: leave out films already in the library. Default all. |
| `limit` | string | no |  | Films to return, at most 200. Default 60. |
| `norating` | string | no |  | Certifications to leave out, comma-separated. |
| `offset` | string | no |  | Films to skip. |
| `only` | string | no |  | A source list id from GET /api/discover/meta. |
| `q` | string | no |  | Words to find in the title, director or cast. |
| `rating` | string | no |  | Certifications to keep, comma-separated. |
| `runtimefrom` | string | no |  | Shortest running time, in minutes. |
| `runtimeto` | string | no |  | Longest running time, in minutes. |
| `skipped` | string | no |  | hide, only or all: films skipped, here or as dropped in the library. Default hide. |
| `sort` | string | no |  | notable, imdb, year, year-asc or title. Default notable. |
| `to` | string | no |  | Latest year. |
| `topic` | string | no |  | A topic id from GET /api/discover/meta. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `votesfrom` | string | no |  | Fewest IMDb votes. |
| `votesto` | string | no |  | Most IMDb votes. |
| `watched` | string | no |  | hide, only or all: films watched. Default hide. |

## dismiss_duplicates

Mark two or more titles as not the same, for the whole family. Returns the pairs, which undismissing takes back.

|  |  |
|---|---|
| Route | [`POST /api/dupes/dismiss`](api.md#post-apidupesdismiss) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ids` | array of string | yes |  | Title ids, from GET /api/library (search_library over MCP). |

## enrich_title

Look the title up with the configured providers now and fill in missing details (refresh: true overwrites what is there). Returns the previous values.

|  |  |
|---|---|
| Route | [`POST /api/titles/{title_id}/enrich`](api.md#post-apititlestitle_idenrich) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `refresh` | boolean | no |  | Overwrite what is there, not just fill in what is missing. |
| `title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

## enrich_title_bulk

Runs enrich_title once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/titles/enrich`](api.md#post-apibulktitlesenrich) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].refresh` | boolean | no |  | Overwrite what is there, not just fill in what is missing. |
| `items[].title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.refresh` | boolean | no |  | Overwrite what is there, not just fill in what is missing. |

## get_prefs

A person's settings that follow them between devices: cards (layout per screen), last_query, default_view and ui.

|  |  |
|---|---|
| Route | [`GET /api/prefs`](api.md#get-apiprefs) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## get_title

Everything about one title, with the person's state on it (my_state) and who in the family has watched or loved it (family).

|  |  |
|---|---|
| Route | [`GET /api/titles/{title_id}`](api.md#get-apititlestitle_id) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## get_vocab

The fixed words: statuses, lookup kinds, and the canonical genre names.

|  |  |
|---|---|
| Route | [`GET /api/vocab`](api.md#get-apivocab) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## import_items

Create titles from rows ({fields, state}, at most 200 per call), skipping any the library certainly has unless skip_dupes is false, and put them on the person's lists. Send the same batch_id for every call of one import; undoing the import takes the whole batch back.

|  |  |
|---|---|
| Route | [`POST /api/import/items`](api.md#post-apiimportitems) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | string | no |  | The same for every call of one import, so it is undone as one. Default: a new one. |
| `rows` | array of object | yes |  | Up to 200 rows, each {fields, state}, as POST /api/import/parse gives them. |
| `skip_dupes` | boolean | no | default `true` | Skip rows the library certainly has. Default true. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## import_parse

Read a pasted list or a file's text (format auto, outline, csv or json) into rows of title fields, each with its likeliest duplicate (dupe). Writes nothing: send the rows wanted to POST /api/import/items.

|  |  |
|---|---|
| Route | [`POST /api/import/parse`](api.md#post-apiimportparse) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `format` | string | no | default `auto` | auto, outline, csv or json. Default auto. |
| `status` | string | no | default `queue` | The status rows without one get: queue, watching, watched or dropped. Default queue. |
| `text` | string | yes |  | A pasted list, or a file's text. |
| `type` | string | no | default `movie` | The type id titles without one get. Default movie. |

## jobs_status

What the server is doing in the background (filling in titles, IMDb ratings, the catalogue), the poster cache, and whether lookups are on.

|  |  |
|---|---|
| Route | [`GET /api/jobs`](api.md#get-apijobs) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## label_my_session

Give one of your devices a name (at most 80 characters; empty clears it). expect, when given, is the name you think it has now.

|  |  |
|---|---|
| Route | [`POST /api/account/sessions/{session_id}/label`](api.md#post-apiaccountsessionssession_idlabel) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `label` | string | yes | at most 80 characters | At most 80 characters. |
| `session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

## list_duplicates

Groups of library titles that look like the same work, minus pairs marked as different.

|  |  |
|---|---|
| Route | [`GET /api/dupes`](api.md#get-apidupes) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## list_my_sessions

Where your account is signed in, a page at a time: id, when it started and was last seen, the browser, and the name you gave it. Through an API key no device is current. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Route | [`GET /api/account/sessions`](api.md#get-apiaccountsessions) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

## list_playlists

A person's playlists: id, name and how many titles each holds. With playlist_id, that one playlist's titles instead, numbered in its order.

|  |  |
|---|---|
| Route | [`GET /api/playlists`](api.md#get-apiplaylists) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist_id` | integer or null | no | at least 1 | Over MCP only: that one playlist's titles, numbered in its order, instead of the list. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## list_sources

The lists and pages titles were found on, newest first.

|  |  |
|---|---|
| Route | [`GET /api/sources`](api.md#get-apisources) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## list_suggestions

A person's suggestion lists: id, name and how many items each holds. With list_id, that one list's items, numbered, each with its note, IMDb score and whether it is in the library yet.

|  |  |
|---|---|
| Route | [`GET /api/suggestions`](api.md#get-apisuggestions) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `list_id` | integer or null | no | at least 1 | Over MCP only: that one list's items, numbered in its order, instead of the lists. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## list_team

People with an active account, a page at a time: id and display name. Use the id wherever another tool asks for a user. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Route | [`GET /api/team`](api.md#get-apiteam) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `limit` | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

## list_types

The library's sections (Movies, TV, and any the family added), in order.

|  |  |
|---|---|
| Route | [`GET /api/types`](api.md#get-apitypes) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## list_views

A person's saved views: a named query on the library or Discover screen, in their order.

|  |  |
|---|---|
| Route | [`GET /api/views`](api.md#get-apiviews) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## lookup

Identify names, names and years, or links with the configured providers, and say whether the library already has each. Writes nothing. Counts against the per-person lookup allowance (providers.lookups_per_minute); 503 lookups_off while the network is off.

|  |  |
|---|---|
| Route | [`POST /api/resolve`](api.md#post-apiresolve) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `kind` | string | no | default `any` | movie, tv, book, ... or any. |
| `lines` | array of string | yes |  | Up to 25 lines, each a name, a name and year, an IMDb id, or a link (IMDb, Wikipedia, TMDB, TVmaze...). |

## merge_titles

Keep title_id and fold the drop_ids into it: everyone's state, playlists and details move over and the others are deleted. One undo step: undo the merge with the merge_id returned.

|  |  |
|---|---|
| Route | [`POST /api/titles/{title_id}/merge`](api.md#post-apititlestitle_idmerge) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `drop_ids` | array of string | yes |  | Title ids, from GET /api/library (search_library over MCP). |
| `title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

## merge_titles_bulk

Runs merge_titles once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/titles/merge`](api.md#post-apibulktitlesmerge) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].drop_ids` | array of string | no |  | Title ids, from GET /api/library (search_library over MCP). |
| `items[].title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.drop_ids` | array of string | no |  | Title ids, from GET /api/library (search_library over MCP). |

## move_in_playlist

Move one title to position; the rest renumber. Returns the items before, which setting the items takes back.

|  |  |
|---|---|
| Route | [`POST /api/playlists/{playlist_id}/move`](api.md#post-apiplaylistsplaylist_idmove) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `position` | integer | yes | at least 1 | 1-based. |
| `title_id` | string | yes |  | The title to move. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## move_suggestion

Move one item to position; the rest renumber. Returns the items before.

|  |  |
|---|---|
| Route | [`POST /api/suggestions/{list_id}/move`](api.md#post-apisuggestionslist_idmove) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `position` | integer | yes | at least 1 | 1-based. |
| `ref` | string | yes |  | An item's ref: a title id, or cat:<film key>. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## remove_from_playlist

Take titles off a playlist; the rest renumber. Returns the items before, which setting the items takes back.

|  |  |
|---|---|
| Route | [`POST /api/playlists/{playlist_id}/remove`](api.md#post-apiplaylistsplaylist_idremove) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `title_ids` | array of string | yes |  | Title ids, from GET /api/library (search_library over MCP). |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## remove_suggestions

Take items off a suggestion list, by ref. Returns the items before.

|  |  |
|---|---|
| Route | [`POST /api/suggestions/{list_id}/remove`](api.md#post-apisuggestionslist_idremove) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `refs` | array of string | yes |  | Item refs, as GET /api/suggestions gives them. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## rename_account

Change your own display name (1-80 characters). expect, when given, is the name you think it has now; if someone changed it meanwhile the rename is refused with the current name, so nothing is overwritten unseen.

|  |  |
|---|---|
| Route | [`POST /api/account/rename`](api.md#post-apiaccountrename) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes | 1 to 80 characters |  |
| `expect` | string or null | no |  |  |

## rename_playlist

Give a playlist a new name. Returns the previous one.

|  |  |
|---|---|
| Route | [`POST /api/playlists/{playlist_id}/update`](api.md#post-apiplaylistsplaylist_idupdate) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  | Up to 80 characters. |
| `playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## rename_suggestion_list

Give a suggestion list a new name. Returns the previous one.

|  |  |
|---|---|
| Route | [`POST /api/suggestions/{list_id}/update`](api.md#post-apisuggestionslist_idupdate) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `name` | string | yes |  | Up to 80 characters. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## reorder_playlists

Put the playlists in this order (ids: every playlist id, first to last).

|  |  |
|---|---|
| Route | [`POST /api/playlists/reorder`](api.md#post-apiplaylistsreorder) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ids` | array of integer | yes |  | Ids, first to last. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## reorder_suggestion_lists

Put the suggestion lists in this order (ids: every list id, first to last).

|  |  |
|---|---|
| Route | [`POST /api/suggestions/reorder`](api.md#post-apisuggestionsreorder) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ids` | array of integer | yes |  | Ids, first to last. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## reorder_views

Put the saved views in this order (ids: view ids, first to last).

|  |  |
|---|---|
| Route | [`POST /api/views/reorder`](api.md#post-apiviewsreorder) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ids` | array of integer | yes |  | Ids, first to last. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## restore_playlist

Bring back a deleted playlist, within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/playlists/{playlist_id}/restore`](api.md#post-apiplaylistsplaylist_idrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## restore_playlist_bulk

Runs restore_playlist once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/playlists/restore`](api.md#post-apibulkplaylistsrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## restore_source

Bring back a deleted source, within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/sources/{source_id}/restore`](api.md#post-apisourcessource_idrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `source_id` | string | yes |  | A source's id, from GET /api/sources. |

## restore_source_bulk

Runs restore_source once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/sources/restore`](api.md#post-apibulksourcesrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].source_id` | string | yes |  | A source's id, from GET /api/sources. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## restore_suggestion_list

Bring back a deleted suggestion list, within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/suggestions/{list_id}/restore`](api.md#post-apisuggestionslist_idrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## restore_suggestion_list_bulk

Runs restore_suggestion_list once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/suggestions/restore`](api.md#post-apibulksuggestionsrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## restore_title

Bring back a deleted title, within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/titles/{title_id}/restore`](api.md#post-apititlestitle_idrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

## restore_type

Bring back a deleted media type, within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/types/{type_id}/restore`](api.md#post-apitypestype_idrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `type_id` | string | yes |  | A type's id, from GET /api/types. |

## restore_type_bulk

Runs restore_type once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/types/restore`](api.md#post-apibulktypesrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].type_id` | string | yes |  | A type's id, from GET /api/types. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## restore_view

Bring back a deleted saved view, within the undo window.

|  |  |
|---|---|
| Route | [`POST /api/views/{view_id}/restore`](api.md#post-apiviewsview_idrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `view_id` | integer | yes | at least 1 | A view's id, from GET /api/views. |

## restore_view_bulk

Runs restore_view once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/views/restore`](api.md#post-apibulkviewsrestore) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `items[].view_id` | integer | yes | at least 1 | A view's id, from GET /api/views. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## revoke_my_other_sessions

End every session your account has: through an API key there is no current device to keep, so every browser signs in again. API keys keep working. Answers with how many were removed.

|  |  |
|---|---|
| Route | [`POST /api/account/sessions/revoke-others`](api.md#post-apiaccountsessionsrevoke-others) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## revoke_my_session

End one of your signed-in sessions; that browser has to sign in again.

|  |  |
|---|---|
| Route | [`POST /api/account/sessions/{session_id}/revoke`](api.md#post-apiaccountsessionssession_idrevoke) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

## revoke_my_session_bulk

Runs revoke_my_session once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/account/sessions/revoke`](api.md#post-apibulkaccountsessionsrevoke) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## save_prefs

Change settings by section (cards, last_query, default_view, ui): each key given replaces that key within its section, and null removes it. Returns them all.

|  |  |
|---|---|
| Route | [`POST /api/prefs`](api.md#post-apiprefs) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cards` | object | no |  | Each key given replaces that key in the section; null removes it. |
| `default_view` | object | no |  | Each key given replaces that key in the section; null removes it. |
| `last_query` | object | no |  | Each key given replaces that key in the section; null removes it. |
| `ui` | object | no |  | Each key given replaces that key in the section; null removes it. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## save_type

Create a media type, or change one by its id. Movies and TV keep their lookup.

|  |  |
|---|---|
| Route | [`POST /api/types`](api.md#post-apitypes) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `icon` | string | no |  |  |
| `id` | string | yes |  | a-z, 0-9 and -, up to 32; never changes once made. |
| `label` | string | yes |  | Up to 40 characters. |
| `lookup` | string | no | default `other` | What titles of this type are looked up as: movie, tv, book, ... or other. |
| `position` | integer or null | no |  |  |

## search_library

Titles in the family library, with the person's own state on each (status, rating, heart) and who else has watched or loved it. Every argument is optional.

|  |  |
|---|---|
| Route | [`GET /api/library/search`](api.md#get-apilibrarysearch) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `limit` | integer | no | 1 to 500; default `50` | Rows to return. Default 50. |
| `status` | string | no |  | queue, watching, watched, dropped or none, or up_next for the Up next list (queue and watching, newest first). |
| `text` | string | no | at most 200 characters | Words that must all appear in the title, director, cast, genres, tags or notes. |
| `type` | string | no |  | A type id such as movie or tv. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## set_playlist_items

Replace a playlist's titles with items, in order: the undo of add, remove and move. Returns the items before.

|  |  |
|---|---|
| Route | [`POST /api/playlists/{playlist_id}/set`](api.md#post-apiplaylistsplaylist_idset) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of string | yes |  | Every title, in order. |
| `playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## set_state

Change one person's state on a title: status (queue, watching, watched, dropped, or null for off the list), rating 1-10 or null, heart true/false, note, watched_at. Returns the previous values.

|  |  |
|---|---|
| Route | [`POST /api/state/{title_id}`](api.md#post-apistatetitle_id) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `set` | object | yes |  | A person's state: status (queue, watching, watched, dropped, or null), rating 1-10 or null, heart, note, watched_at. |
| `title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## set_states

changes is {title id: {status, rating, heart, note, watched_at}}, up to 2000 titles: a bulk action sends the same change for every id. Returns each title's previous values, which sent back are the undo.

|  |  |
|---|---|
| Route | [`POST /api/state/bulk`](api.md#post-apistatebulk) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `changes` | map of object | yes |  | {title id: {status, rating, heart, note, watched_at}}, up to 2000 titles. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## set_suggestion_items

Replace a list's items, in order: the undo of add, remove, move and note. Returns the items before.

|  |  |
|---|---|
| Route | [`POST /api/suggestions/{list_id}/set`](api.md#post-apisuggestionslist_idset) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | Every item ({ref, note, added_at}), in order. |
| `list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## set_suggestion_note

Replace one item's note (empty clears it). Returns the items before.

|  |  |
|---|---|
| Route | [`POST /api/suggestions/{list_id}/note`](api.md#post-apisuggestionslist_idnote) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `note` | string | yes | at most 200 characters | Why it is suggested, in a line: shown under the card. |
| `ref` | string | yes |  | An item's ref: a title id, or cat:<film key>. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

## set_theme

Switch to another theme from your list (or the defaults), by its id.

|  |  |
|---|---|
| Route | [`POST /api/account/theme`](api.md#post-apiaccounttheme) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `theme_id` | string | yes |  | A theme's id. Empty for the first in the list. |

## set_themes

Replace your whole list of color themes (1 to 40) and pick the one you use. themes: null goes back to following the app's defaults. A theme is the Theme schema in the API reference (config/api.json): id, name, mode light|dark, accent, second, and optional colors as #rrggbb. whoami shows the current list.

|  |  |
|---|---|
| Route | [`POST /api/account/themes`](api.md#post-apiaccountthemes) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | no |  | Which built-in themes this list has seen: the highest since in Theme.builtIn (static/js/theme.js) when it was saved. Built-in themes added after that join the list the browser shows. Left out: 0, the first ones. |
| `theme_id` | string | no |  | The theme you use. |
| `themes` | array of object or null | no |  | Your whole list, 1 to 40 themes. null goes back to following the app's defaults. |
| `themes[].accent` | string | yes |  | The main color: what you can press. |
| `themes[].background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].button` | object or null | no |  | How the theme's buttons look. A choice left out is the default (rounded, normal, raised, normal). |
| `themes[].button.case` | string | no | one of `normal`, `upper` |  |
| `themes[].button.depth` | string | no | one of `flat`, `raised`, `glossy` |  |
| `themes[].button.shape` | string | no | one of `square`, `soft`, `rounded`, `pill` |  |
| `themes[].button.weight` | string | no | one of `normal`, `medium`, `bold` |  |
| `themes[].dark` | object or null | no |  | A light theme's colors for dark mode, kept while it is light. Switching the theme to dark swaps them in. A light theme's light (or a dark theme's dark) is dropped. |
| `themes[].dark.accent` | string | yes |  | The main color: what you can press. |
| `themes[].dark.background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].dark.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].dark.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].dark.surface` | string | no |  | Cards. Left out: the mode's own. |
| `themes[].id` | string | yes |  | Lower-case letters, digits, - and _, up to 32. |
| `themes[].light` | object or null | no |  | A dark theme's colors for light mode, kept while it is dark. Switching the theme to light swaps them in. |
| `themes[].light.accent` | string | yes |  | The main color: what you can press. |
| `themes[].light.background` | string | no |  | The page. Left out: the mode's own. |
| `themes[].light.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].light.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].light.surface` | string | no |  | Cards. Left out: the mode's own. |
| `themes[].mode` | string | yes | one of `light`, `dark` |  |
| `themes[].name` | string | yes |  | 1 to 60 characters. |
| `themes[].overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `themes[].second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `themes[].surface` | string | no |  | Cards. Left out: the mode's own. |

## set_verdict

Set the person's verdict on a film: skip hides it from them only, seen marks it seen, null clears it.

|  |  |
|---|---|
| Route | [`POST /api/discover/verdict`](api.md#post-apidiscoververdict) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `key` | string | yes |  | The film's key, from GET /api/discover. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `verdict` | string or null | no |  | skip (hide it from you), seen, or null to clear. |

## undismiss_duplicates

Forget pairs that dismissing recorded.

|  |  |
|---|---|
| Route | [`POST /api/dupes/undismiss`](api.md#post-apidupesundismiss) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `pairs` | array of string | yes |  | Pairs from dismissing. |

## undo_import

Delete the titles one import created, and the importer's state on them.

|  |  |
|---|---|
| Route | [`POST /api/import/{batch_id}/undo`](api.md#post-apiimportbatch_idundo) |
| Read only | no |
| Destructive | yes |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | string | yes |  | From POST /api/import/items. |

## undo_merge

Put a merge back as it was: the dropped titles, and everyone's state and playlists.

|  |  |
|---|---|
| Route | [`POST /api/merges/{merge_id}/undo`](api.md#post-apimergesmerge_idundo) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `merge_id` | string | yes |  | From merging titles. |

## undo_merge_bulk

Runs undo_merge once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/merges/undo`](api.md#post-apibulkmergesundo) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].merge_id` | string | yes |  | From merging titles. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

## update_source

Change a source's link, title, note or tags. Returns the previous values.

|  |  |
|---|---|
| Route | [`POST /api/sources/{source_id}/update`](api.md#post-apisourcessource_idupdate) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `note` | string | no |  | Up to 2000 characters. |
| `source_id` | string | yes |  | A source's id, from GET /api/sources. |
| `tags` | array of string | no |  | Up to 20. |
| `title` | string | no |  | Up to 300 characters. |
| `url` | string | no |  | An http(s) link. |

## update_title

Change shared details of a title (title, year, type, tags, notes, links, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url). Returns the previous values.

|  |  |
|---|---|
| Route | [`POST /api/titles/{title_id}/update`](api.md#post-apititlestitle_idupdate) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `set` | object | yes |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |
| `title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

## update_title_bulk

Runs update_title once per item: items holds each call's arguments, shared the arguments they have in common (an item's own win). In order; one failing does not stop the rest, and the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Route | [`POST /api/bulk/titles/update`](api.md#post-apibulktitlesupdate) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `items[].set` | object | no |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |
| `items[].title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `shared.set` | object | no |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |

## update_view

Change a saved view's name, query, card layout or icon. Returns the previous values.

|  |  |
|---|---|
| Route | [`POST /api/views/{view_id}/update`](api.md#post-apiviewsview_idupdate) |
| Read only | no |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `card` | object or null | no |  | How cards look in this view. |
| `icon` | string | no |  |  |
| `name` | string | no |  |  |
| `query` | string | no |  | The screen's address, such as #library/all/queue?runtime=..100. |
| `scope` | string | no |  | The library section it is on. |
| `screen` | string | no |  | library or discover. |
| `user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `view_id` | integer | yes | at least 1 | A view's id, from GET /api/views. |

## whoami

The account this API key belongs to, the role it acts with (role -- never higher than the key's own scope), and the account's own role.

|  |  |
|---|---|
| Route | [`GET /api/me`](api.md#get-apime) |
| Read only | yes |
| Destructive | no |

**Arguments**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|

## HTTP only

Routes an API key may call that have no tool, and why.

| Route | Why |
|---|---|
| [`GET /api/admin/users/{user_id}/keys`](api.md#get-apiadminusersuser_idkeys) | Manages API keys, which no MCP tool does. |
| [`GET /api/api.json`](api.md#get-apiapijson) | The API reference itself; GET /api/mcp.json is the MCP one. |
| [`GET /api/api.md`](api.md#get-apiapimd) | The API reference itself, for people; GET /api/api.json is the same as JSON. |
| [`GET /api/export`](api.md#get-apiexport) | a file download |
| [`GET /api/img/{key}`](api.md#get-apiimgkey) | image bytes |
| [`GET /api/library`](api.md#get-apilibrary) | the whole library for the browser; search_library is the agent's version |
| [`GET /api/mcp.json`](api.md#get-apimcpjson) | The MCP reference itself; tools/list gives the same list. |
| [`GET /api/mcp.md`](api.md#get-apimcpmd) | The MCP reference itself, for people; tools/list gives the same list. |
| [`POST /api/admin/keys/{key_id}/revoke`](api.md#post-apiadminkeyskey_idrevoke) | Manages API keys, which no MCP tool does. |
| [`POST /api/admin/users/{user_id}/keys`](api.md#post-apiadminusersuser_idkeys) | Makes an API key, which no MCP tool does. |
| [`POST /api/keys/self/rotate`](api.md#post-apikeysselfrotate) | Makes an API key's credential, which no MCP tool does. |
| [`POST /api/logout`](api.md#post-apilogout) | Ends a browser session; a key has none to end. |
| [`POST /api/logs/events`](api.md#post-apilogsevents) | The browser's own activity reports (track.js), not an action. |
| [`POST /mcp`](api.md#post-mcp) | The MCP endpoint itself. |
