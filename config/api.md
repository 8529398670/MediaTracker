# Media Tracker API

Every route this server answers, apart from the pages at /login/*, /join/* and /docs/*. Generated from the code by scripts/api_docs.sh: an app's own routes get their docs the same way, and a test fails until they do.

This file is generated: do not edit it. Change the docs next to the handlers and run `scripts/api_docs.sh`.

## Contents

- [Calling the API](#calling-the-api)
- [Errors](#errors)
- [Account](#account)
- [Sign-in](#sign-in)
- [API keys](#api-keys)
- [Admin](#admin)
- [Invite links](#invite-links)
- [Owner](#owner)
- [Monitoring](#monitoring)
- [Discover](#discover)
- [Jobs](#jobs)
- [Library](#library)
- [Playlists](#playlists)
- [Settings](#settings)
- [Suggestions](#suggestions)
- [Schemas](#schemas)

## Calling the API

| Way in | How |
|---|---|
| Browser session | A browser session. Its POSTs carry csrf_token in the body. The cookie's name is server.cookie_name, with the __Host- prefix while server.secure_cookies is on. |
| API key | An API key, as Authorization: Bearer <id>.<secret>. |

## Errors

An error reply is a JSON object whose `error` says what went wrong.

| Status | Meaning | Body |
|---|---|---|
| 400 | The request was refused as it stands. | [`Error`](#error) |
| 401 | Not signed in. | [`Error`](#error) |
| 403 | Not allowed, or a bad csrf_token. | [`Error`](#error) |
| 404 | No such thing, or this feature is switched off. | [`Error`](#error) |
| 409 | The record has moved on: an undo too late, or a stale edit. | [`Error`](#error) |
| 429 | Too many requests. | [`Error`](#error) |
| 503 | In maintenance mode. Retry-After says when to try again. | [`Maintenance`](#maintenance) |

## Account

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/account/login-link`](#post-apiaccountlogin-link) | A login link for yourself | browser session or API key, anyone signed in |
| POST | [`/api/account/login-link/cancel`](#post-apiaccountlogin-linkcancel) | Stop your own login link working | browser session or API key, anyone signed in |
| POST | [`/api/account/password`](#post-apiaccountpassword) | Set or clear your password | browser session only, anyone signed in |
| POST | [`/api/account/pin`](#post-apiaccountpin) | Set or clear your PIN | browser session only, anyone signed in |
| POST | [`/api/account/rename`](#post-apiaccountrename) | Rename your account | browser session or API key, anyone signed in |
| GET | [`/api/account/sessions`](#get-apiaccountsessions) | Your signed-in devices | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/revoke-others`](#post-apiaccountsessionsrevoke-others) | Sign out every other device | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/{session_id}/label`](#post-apiaccountsessionssession_idlabel) | Name one of your devices | browser session or API key, anyone signed in |
| POST | [`/api/account/sessions/{session_id}/revoke`](#post-apiaccountsessionssession_idrevoke) | Sign out one of your devices | browser session or API key, anyone signed in |
| POST | [`/api/account/theme`](#post-apiaccounttheme) | Pick your theme | browser session or API key, anyone signed in |
| POST | [`/api/account/themes`](#post-apiaccountthemes) | Replace your own themes | browser session or API key, anyone signed in |
| POST | [`/api/account/two-factor/confirm`](#post-apiaccounttwo-factorconfirm) | Turn two-factor on | browser session only, anyone signed in |
| POST | [`/api/account/two-factor/disable`](#post-apiaccounttwo-factordisable) | Turn two-factor off | browser session only, anyone signed in |
| POST | [`/api/account/two-factor/start`](#post-apiaccounttwo-factorstart) | Begin two-factor setup | browser session only, anyone signed in |
| POST | [`/api/bulk/account/sessions/revoke`](#post-apibulkaccountsessionsrevoke) | Sign out one of your devices, for many at once | browser session or API key, anyone signed in |
| GET | [`/api/language`](#get-apilanguage) | The UI's text | anyone |
| POST | [`/api/logout`](#post-apilogout) | Sign out | browser session or API key, anyone signed in |
| POST | [`/api/logs/events`](#post-apilogsevents) | Record what happened on the page | browser session or API key, anyone signed in |
| GET | [`/api/me`](#get-apime) | Who am I | browser session or API key, anyone signed in |
| GET | [`/api/team`](#get-apiteam) | List team | browser session or API key, anyone signed in |

### POST /api/account/login-link

A login link for yourself

A link that signs your own account in on a browser or another device. An API key may ask only if your account let it, from a browser session (POST /api/keys/{key_id}/sign-in); its link works once, for at most 15 minutes.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`create_my_login_link`](mcp.md#create_my_login_link) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |

### POST /api/account/login-link/cancel

Stop your own login link working

Void your account's live login link without making a new one. Devices it already signed in stay signed in. Answers with removed: 0 or 1.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`cancel_my_login_link`](mcp.md#cancel_my_login_link) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  | Links removed: 0 or 1. |

### POST /api/account/password

Set or clear your password

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | no |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `password_digest` | string | yes |  |  |
| `username` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `has_password` | boolean | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/account/pin

Set or clear your PIN

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `pin` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `has_pin` | boolean | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/account/rename

Rename your account

Change your own display name (1-80 characters). expect, when given, is the name you think it has now; if someone changed it meanwhile the rename is refused with the current name, so nothing is overwritten unseen.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`rename_account`](mcp.md#rename_account) |
| Errors | 400, 401, 403, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters |  |
| `expect` | string or null | no |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### GET /api/account/sessions

Your signed-in devices

Where your account is signed in, a page at a time: id, when it started and was last seen, the browser, and the name you gave it. Through an API key no device is current. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_my_sessions`](mcp.md#list_my_sessions) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `sessions` | array of [`Session`](#session) | yes |  |  |
| `total` | integer | yes |  |  |

### POST /api/account/sessions/revoke-others

Sign out every other device

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`revoke_my_other_sessions`](mcp.md#revoke_my_other_sessions) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  |  |

### POST /api/account/sessions/{session_id}/label

Name one of your devices

Give one of your devices a name (at most 80 characters; empty clears it). expect, when given, is the name you think it has now.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`label_my_session`](mcp.md#label_my_session) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `label` | string | yes | at most 80 characters | At most 80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `label` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/account/sessions/{session_id}/revoke

Sign out one of your devices

End one of your signed-in sessions; that browser has to sign in again.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`revoke_my_session`](mcp.md#revoke_my_session) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/account/theme

Pick your theme

Switch to another theme from your list (or the defaults), by its id.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_theme`](mcp.md#set_theme) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `theme_id` | string | yes |  | A theme's id. Empty for the first in the list. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `theme_id` | string | yes |  |  |

### POST /api/account/themes

Replace your own themes

Replace your whole list of color themes (1 to 40) and pick the one you use. themes: null goes back to following the app's defaults. A theme is the Theme schema in the API reference (config/api.json): id, name, mode light|dark, accent, second, and optional colors as #rrggbb.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_themes`](mcp.md#set_themes) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | no |  | Which built-in themes this list has seen: the highest since in Theme.builtIn (static/js/theme.js) when it was saved. Built-in themes added after that join the list the browser shows. Left out: 0, the first ones. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `theme_id` | string | no |  | The theme you use. |
| `themes` | array of [`Theme`](#theme) or null | no |  | Your whole list, 1 to 40 themes. null goes back to following the app's defaults. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `theme_id` | string | yes |  |  |
| `themes` | array of [`Theme`](#theme) or null | yes |  | What you now see; null while the built-in themes apply. |
| `themes_builtins` | integer | yes |  | Which built-in themes that list has seen (see builtins on POST /api/account/themes). |
| `themes_custom` | boolean | yes |  |  |

### POST /api/account/two-factor/confirm

Turn two-factor on

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `recovery_codes` | array of string | yes |  |  |

### POST /api/account/two-factor/disable

Turn two-factor off

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/account/two-factor/start

Begin two-factor setup

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `secret` | string | yes |  |  |

### POST /api/bulk/account/sessions/revoke

Sign out one of your devices, for many at once

Runs POST /api/account/sessions/{session_id}/revoke once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`revoke_my_session_bulk`](mcp.md#revoke_my_session_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### GET /api/language

The UI's text

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

An empty object.

### POST /api/logout

Sign out

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: Ends a browser session; a key has none to end. |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/logs/events

Record what happened on the page

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The browser's own activity reports (track.js), not an action. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `events` | array of object | yes |  |  |
| `tab` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accepted` | integer | yes |  |  |

### GET /api/me

Who am I

The account this API key belongs to, the role it acts with (role -- never higher than the key's own scope), and the account's own role.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`whoami`](mcp.md#whoami) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

[`Me`](#me).

### GET /api/team

List team

People with an active account, a page at a time: id and display name.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_team`](mcp.md#list_team) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `members` | array of [`Member`](#member) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

## Sign-in

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/login`](#post-apilogin) | Redeem a login link | anyone |
| GET | [`/api/login/options`](#get-apiloginoptions) | What sign-in offers | anyone |
| POST | [`/api/login/password`](#post-apiloginpassword) | Sign in with a password | anyone |
| POST | [`/api/login/two-factor`](#post-apilogintwo-factor) | Finish a sign-in with a code | anyone |

### POST /api/login

Redeem a login link

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |

**Reply 200**: Success

[`SignIn`](#signin).

### GET /api/login/options

What sign-in offers

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `passwords` | boolean | yes |  |  |
| `salt` | string | no |  |  |
| `two_factor` | boolean | yes |  |  |

### POST /api/login/password

Sign in with a password

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `password_digest` | string | yes |  |  |
| `username` | string | yes |  |  |

**Reply 200**: Success

[`SignIn`](#signin).

### POST /api/login/two-factor

Finish a sign-in with a code

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `challenge` | string | yes |  |  |
| `code` | string | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

## API keys

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/admin/keys`](#get-apiadminkeys) | Every key in the app | browser session only, admins |
| POST | [`/api/admin/keys`](#post-apiadminkeys) | Create a key that acts as someone else | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/delete`](#post-apiadminkeyskey_iddelete) | Delete anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/expiry`](#post-apiadminkeyskey_idexpiry) | Change when anyone's key expires | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/rename`](#post-apiadminkeyskey_idrename) | Rename anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/restore`](#post-apiadminkeyskey_idrestore) | Undo deleting anyone's key | browser session only, admins |
| POST | [`/api/admin/keys/{key_id}/revoke`](#post-apiadminkeyskey_idrevoke) | Revoke anyone's key | browser session or API key, admins |
| GET | [`/api/admin/users/{user_id}/keys`](#get-apiadminusersuser_idkeys) | An account's keys | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/keys`](#post-apiadminusersuser_idkeys) | Make a key for an account | browser session or API key, admins |
| GET | [`/api/keys`](#get-apikeys) | Your API keys | browser session only, anyone signed in |
| POST | [`/api/keys`](#post-apikeys) | Create an API key | browser session only, anyone signed in |
| POST | [`/api/keys/self/rotate`](#post-apikeysselfrotate) | Rotate the calling key | API key only, anyone signed in |
| POST | [`/api/keys/{key_id}/delete`](#post-apikeyskey_iddelete) | Delete one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/expiry`](#post-apikeyskey_idexpiry) | Change when one of your keys expires | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/mint-keys`](#post-apikeyskey_idmint-keys) | Let one of your keys make keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/rename`](#post-apikeyskey_idrename) | Rename one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/restore`](#post-apikeyskey_idrestore) | Undo deleting one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/revoke`](#post-apikeyskey_idrevoke) | Revoke one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/rotate`](#post-apikeyskey_idrotate) | Rotate one of your keys | browser session only, anyone signed in |
| POST | [`/api/keys/{key_id}/sign-in`](#post-apikeyskey_idsign-in) | Let one of your keys make sign-in links | browser session only, anyone signed in |

### GET /api/admin/keys

Every key in the app

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep keys whose name or owner contains this, in any case. |
| `live` | query | string | no | one of `true` | Leave out revoked and expired keys. |
| `sort` | query | string | no | one of `display_name`, `name`, `role`, `last_used_at`, `expires_at`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `keys` | array of [`APIKey`](#apikey) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/admin/keys

Create a key that acts as someone else

Any admin may do this for an ordinary user, and only the owner for another admin. Nobody may do it for the owner. The key records who made it and shows that to the person it acts as.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer or null | no | 0 to 3650 | Absent or null: the configured default. 0: never expires. |
| `name` | string | yes | 1 to 80 characters |  |
| `role` | string | no | one of `admin`, `user`, `viewer`; default `user` |  |
| `user_id` | integer | yes | at least 1 |  |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### POST /api/admin/keys/{key_id}/delete

Delete anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/keys/{key_id}/expiry

Change when anyone's key expires

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer | yes | 0 to 3650 | Counted from now. 0 means it never expires. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/admin/keys/{key_id}/rename

Rename anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `name` | string | yes | 1 to 80 characters | 1-80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/admin/keys/{key_id}/restore

Undo deleting anyone's key

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/admin/keys/{key_id}/revoke

Revoke anyone's key

Stops the key at once, and every key it made, down the chain. Needs a browser session or a key with may_mint_keys (any other key gets 403 key_minting_off), which may not revoke the owner's keys.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | None, HTTP only: Manages API keys, which no MCP tool does. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/admin/users/{user_id}/keys

An account's keys

One account's keys, revoked and expired ones included, newest first. Each row says which key minted it (minted_by_key, empty when a person made it). Needs a browser session or a key with may_mint_keys; any other key gets 403 key_minting_off. Follows the owner ladder: nobody lists the owner's keys this way, and only the owner lists another admin's.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | None, HTTP only: Manages API keys, which no MCP tool does. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `keys` | array of [`APIKey`](#apikey) | yes |  |  |

### POST /api/admin/users/{user_id}/keys

Make a key for an account

Needs a browser session or a key the owner allowed to make keys (may_mint_keys); any other key gets 403 key_minting_off. The role is capped at the account's own; expires_in_days is required (1-365). Never for the owner. The new key records the key that made it, can never make keys or sign-in links itself, and is revoked when that key is revoked or deleted. Answers with the key and its credential, shown only now.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | None, HTTP only: Makes an API key, which no MCP tool does. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer | yes | 1 to 365 | Required: 1-365. A minted key always expires. |
| `name` | string | yes | 1 to 80 characters |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` | Capped at the account's own role. |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### GET /api/keys

Your API keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep keys whose name contains this, in any case. |
| `live` | query | string | no | one of `true` | Leave out revoked and expired keys. |
| `sort` | query | string | no | one of `name`, `role`, `last_used_at`, `expires_at`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `keys` | array of [`APIKey`](#apikey) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/keys

Create an API key

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer or null | no | 0 to 3650 | Absent or null: the configured default. 0: never expires. |
| `name` | string | yes | 1 to 80 characters |  |
| `role` | string | no | one of `admin`, `user`, `viewer`; default `user` |  |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### POST /api/keys/self/rotate

Rotate the calling key

Gives the calling key a new secret and answers its new credential, shown only now. The old secret stops working at once. The key's id, name, role, grants, lineage and expiry stay as they are, so the keys and links it made keep working; rotating never extends the expiry. A viewer key may call it.

|  |  |
|---|---|
| Who may call | API key only, anyone signed in |
| MCP tool | None, HTTP only: Makes an API key's credential, which no MCP tool does. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`RotatedKey`](#rotatedkey).

### POST /api/keys/{key_id}/delete

Delete one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/keys/{key_id}/expiry

Change when one of your keys expires

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_days` | integer | yes | 0 to 3650 | Counted from now. 0 means it never expires. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/keys/{key_id}/mint-keys

Let one of your keys make keys

Owner only, on one of your own admin-role keys. When on, the key may make keys for other accounts (never the owner's) through POST /api/admin/users/{user_id}/keys, list them, and revoke them. Each key it makes records it, and revoking or deleting this key revokes them all.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `may_mint_keys` | boolean | yes |  | true lets this key make, list and revoke other accounts' keys, each recording this key and revoked with it. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/keys/{key_id}/rename

Rename one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The name you think it has. Answers 409 if it has another. |
| `name` | string | yes | 1 to 80 characters | 1-80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/keys/{key_id}/restore

Undo deleting one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`APIKey`](#apikey).

### POST /api/keys/{key_id}/revoke

Revoke one of your keys

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/keys/{key_id}/rotate

Rotate one of your keys

The owner only: gives one of the owner's own keys a new secret and answers its new credential, shown only now. The old secret stops working at once; nothing else about the key changes.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`RotatedKey`](#rotatedkey).

### POST /api/keys/{key_id}/sign-in

Let one of your keys make sign-in links

Off by default. When on, the key may ask POST /api/account/login-link for a link that signs your account in on a browser, which then can do everything you can, including what keys may not. The link works once, for at most 15 minutes.

|  |  |
|---|---|
| Who may call | browser session only, anyone signed in |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key_id` | path | string | yes |  | The key's id, from GET /api/keys (GET /api/admin/keys for anyone's). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `may_sign_in` | boolean | yes |  | true lets the key make a login link for your account: one that works once, for at most 15 minutes. |

**Reply 200**: Success

[`APIKey`](#apikey).

## Admin

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/admin/theme-defaults`](#get-apiadmintheme-defaults) | Default themes | browser session or API key, admins |
| POST | [`/api/admin/theme-defaults`](#post-apiadmintheme-defaults) | Replace the default themes | browser session or API key, admins |
| GET | [`/api/admin/users`](#get-apiadminusers) | List users | browser session or API key, admins |
| POST | [`/api/admin/users`](#post-apiadminusers) | Create an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/cancel-login-link`](#post-apiadminusersuser_idcancel-login-link) | Stop an account's login link working | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/delete`](#post-apiadminusersuser_iddelete) | Delete an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/disabled`](#post-apiadminusersuser_iddisabled) | Disable or enable a user | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/expiry`](#post-apiadminusersuser_idexpiry) | Set when an account expires | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/reissue-login`](#post-apiadminusersuser_idreissue-login) | A new login link for an account | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/rename`](#post-apiadminusersuser_idrename) | Rename someone | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/reset-two-factor`](#post-apiadminusersuser_idreset-two-factor) | Turn off an account's two-factor | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/revoke-access`](#post-apiadminusersuser_idrevoke-access) | Revoke a user's access | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/role`](#post-apiadminusersuser_idrole) | Change an account's role | browser session or API key, admins |
| GET | [`/api/admin/users/{user_id}/sessions`](#get-apiadminusersuser_idsessions) | An account's signed-in devices | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/sessions/{session_id}/revoke`](#post-apiadminusersuser_idsessionssession_idrevoke) | Sign out one of an account's devices | browser session or API key, admins |
| POST | [`/api/admin/users/{user_id}/showing`](#post-apiadminusersuser_idshowing) | Set an account's Showing picker | browser session only, admins |
| POST | [`/api/bulk/admin/users/cancel-login-link`](#post-apibulkadminuserscancel-login-link) | Stop an account's login link working, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/delete`](#post-apibulkadminusersdelete) | Delete an account, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/disabled`](#post-apibulkadminusersdisabled) | Disable or enable a user, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/reset-two-factor`](#post-apibulkadminusersreset-two-factor) | Turn off an account's two-factor, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/revoke-access`](#post-apibulkadminusersrevoke-access) | Revoke a user's access, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/role`](#post-apibulkadminusersrole) | Change an account's role, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/users/sessions/revoke`](#post-apibulkadminuserssessionsrevoke) | Sign out one of an account's devices, for many at once | browser session or API key, admins |

### GET /api/admin/theme-defaults

Default themes

The theme list everyone without their own list sees. themes is null while the built-in ones apply.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_get_theme_defaults`](mcp.md#admin_get_theme_defaults) |
| Errors | 401, 403, 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | yes |  | Which built-in themes that list has seen (see builtins on POST /api/account/themes). |
| `themes` | array of [`Theme`](#theme) or null | yes |  | null while the built-in themes apply. |

### POST /api/admin/theme-defaults

Replace the default themes

Replace the theme list everyone without their own list sees, 1 to 40 themes in the Theme schema of the API reference. null puts the built-in themes back.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_theme_defaults`](mcp.md#admin_set_theme_defaults) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | no |  | Which built-in themes this list has seen: the highest since in Theme.builtIn (static/js/theme.js) when it was saved. Built-in themes added after that join the list the browser shows. Left out: 0, the first ones. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `themes` | array of [`Theme`](#theme) or null | no |  | 1 to 40 themes. null goes back to the built-in ones. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `builtins` | integer | yes |  | Which built-in themes that list has seen (see builtins on POST /api/account/themes). |
| `ok` | boolean | yes |  |  |
| `themes` | array of [`Theme`](#theme) or null | yes |  |  |

### GET /api/admin/users

List users

Accounts, a page at a time, including disabled ones, with each one's role and which is the owner. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_list_users`](mcp.md#admin_list_users) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep accounts whose name or username contains this, in any case. |
| `sort` | query | string | no | one of `display_name`, `role`, `disabled`, `created_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |
| `users` | array of [`User`](#user) | yes |  |  |

### POST /api/admin/users

Create an account

Make a new account and its first login link, to hand to the person. role is admin, user or viewer (reads only). account_expires_at, when given, is when the account stops working. Answers with user_id and the link.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_create_user`](mcp.md#admin_create_user) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `account_expires_at` | string (date-time) or null | no |  | When the account stops working (RFC 3339). Left out: never. expires_in_minutes is the login link's expiry, not this. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters |  |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `kind` | string | no | one of `person`, `service`; default `person` | person, the default. service is refused (403 service_account): a service account is made by Connect on the owner's API keys screen. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |
| `user_id` | integer | yes |  |  |

### POST /api/admin/users/{user_id}/cancel-login-link

Stop an account's login link working

Void an account's live login link without making a new one: a link that went somewhere it should not have.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_cancel_login_link`](mcp.md#admin_cancel_login_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | integer | yes |  | Links removed: 0 or 1. |

### POST /api/admin/users/{user_id}/delete

Delete an account

Remove an account for good, with its sessions, login link and API keys.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_delete_user`](mcp.md#admin_delete_user) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `removed` | [`Revoked`](#revoked) | yes |  |  |

### POST /api/admin/users/{user_id}/disabled

Disable or enable a user

Switch an account off (disabled: true) or back on (false). Disabling signs it out everywhere and voids its live login link; its API keys stop working while it is off. Reversible. The owner and your own account cannot be disabled.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_user_disabled`](mcp.md#admin_set_user_disabled) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `disabled` | boolean | yes |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/expiry

Set when an account expires

expires_at is when the account stops working (RFC 3339), or null for never. Once it passes the account counts as disabled: sign-in, its sessions and its keys stop, and housekeeping disables it and revokes its access. A later expiry does not re-enable an account housekeeping already disabled. It must be in the future. The owner's account never expires, nobody sets their own, and only the owner sets an admin's.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_user_expiry`](mcp.md#admin_set_user_expiry) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_at` | string (date-time) or null | yes |  | When the account stops working (RFC 3339), or null for never. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/reissue-login

A new login link for an account

For someone who lost their device or their link: a fresh login link for their account.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_reissue_login`](mcp.md#admin_reissue_login) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expires_in_minutes` | integer or null | no | 0 to 525600 | 0 never expires. Default auth.login_token_ttl_seconds for a link that works once, auth.multi_use_login_token_ttl_seconds otherwise. |
| `max_uses` | integer or null | no | 0 to 1000 | Sign-ins the link allows: 1-1000, or 0 for unlimited. Default 1. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `expires_in_seconds` | integer | yes |  | 0 when it never expires. |
| `login_path` | string | yes |  | Path of the login link. A credential: treat it like a password. |
| `max_uses` | integer | yes |  | 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/rename

Rename someone

Change another account's display name (1-80 characters). Only the owner renames an admin. expect, when given, is the name you think it has now; if it changed meanwhile the rename is refused with the current name.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_rename_user`](mcp.md#admin_rename_user) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `display_name` | string | yes | 1 to 80 characters | 1-80 characters. |
| `expect` | string or null | no |  | The name you think they have. Answers 409 if it is another. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/reset-two-factor

Turn off an account's two-factor

For someone who lost both their phone and their recovery codes: switches their two-factor sign-in off so a login link lets them in again. Only the owner resets an admin's; the owner's is reset from a shell.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_reset_two_factor`](mcp.md#admin_reset_two_factor) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/revoke-access

Revoke a user's access

For an account that may be compromised: ends every session and voids its live login link and every API key it holds, at once.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_access`](mcp.md#admin_revoke_access) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `revoked` | [`Revoked`](#revoked) | yes |  |  |

### POST /api/admin/users/{user_id}/role

Change an account's role

Make an account an admin, an ordinary user, or a viewer, who may read but change nothing. Only the owner takes an admin's rights away; the owner is always an admin, and nobody changes their own role. Becoming an admin ends the account's sessions and live login link.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_user_role`](mcp.md#admin_set_user_role) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `role` | string | yes |  |  |

### GET /api/admin/users/{user_id}/sessions

An account's signed-in devices

Where an account is signed in: every session, with when it started and was last seen. Addresses are shown to the owner and service accounts only. Nobody sees the owner's, and only the owner sees another admin's.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_list_user_sessions`](mcp.md#admin_list_user_sessions) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `sessions` | array of [`Session`](#session) | yes |  |  |
| `total` | integer | yes |  |  |

### POST /api/admin/users/{user_id}/sessions/{session_id}/revoke

Sign out one of an account's devices

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_user_session`](mcp.md#admin_revoke_user_session) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `session_id` | path | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/users/{user_id}/showing

Set an account's Showing picker

Give an ordinary account the Showing picker (or take it away), say whose lists it starts on, and optionally lock it there. Admins always have the picker.

|  |  |
|---|---|
| Who may call | browser session only, admins |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `can_show_others` | boolean | yes |  | Give the account the Showing picker, or take it away. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `default_subject` | integer or null | no |  | Whose lists it starts on: a user id, or null for its own. |
| `showing_locked` | boolean | no |  | Fix the picker on default_subject, so it cannot be changed. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `can_show_others` | boolean | yes |  |  |
| `default_subject` | integer or null | yes |  |  |
| `ok` | boolean | yes |  |  |
| `showing_locked` | boolean | yes |  |  |

### POST /api/bulk/admin/users/cancel-login-link

Stop an account's login link working, for many at once

Runs POST /api/admin/users/{user_id}/cancel-login-link once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_cancel_login_link_bulk`](mcp.md#admin_cancel_login_link_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/delete

Delete an account, for many at once

Runs POST /api/admin/users/{user_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_delete_user_bulk`](mcp.md#admin_delete_user_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/disabled

Disable or enable a user, for many at once

Runs POST /api/admin/users/{user_id}/disabled once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_user_disabled_bulk`](mcp.md#admin_set_user_disabled_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].disabled` | boolean | no |  |  |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.disabled` | boolean | no |  |  |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/reset-two-factor

Turn off an account's two-factor, for many at once

Runs POST /api/admin/users/{user_id}/reset-two-factor once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_reset_two_factor_bulk`](mcp.md#admin_reset_two_factor_bulk) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/revoke-access

Revoke a user's access, for many at once

Runs POST /api/admin/users/{user_id}/revoke-access once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_access_bulk`](mcp.md#admin_revoke_access_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/role

Change an account's role, for many at once

Runs POST /api/admin/users/{user_id}/role once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_user_role_bulk`](mcp.md#admin_set_user_role_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].role` | string | no | one of `admin`, `user`, `viewer` |  |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.role` | string | no | one of `admin`, `user`, `viewer` |  |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/users/sessions/revoke

Sign out one of an account's devices, for many at once

Runs POST /api/admin/users/{user_id}/sessions/{session_id}/revoke once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_user_session_bulk`](mcp.md#admin_revoke_user_session_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].session_id` | string | yes |  | The device's id, from GET /api/account/sessions or GET /api/admin/users/{user_id}/sessions (list_my_sessions or admin_list_user_sessions over MCP). |
| `items[].user_id` | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

## Invite links

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/admin/invite-links`](#get-apiadmininvite-links) | List invite links | browser session or API key, admins |
| POST | [`/api/admin/invite-links`](#post-apiadmininvite-links) | Create an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/delete`](#post-apiadmininvite-linkslink_iddelete) | Delete an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/limits`](#post-apiadmininvite-linkslink_idlimits) | Change an invite link's places and expiry | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/rename`](#post-apiadmininvite-linkslink_idrename) | Rename an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/restore`](#post-apiadmininvite-linkslink_idrestore) | Undo deleting an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/revoke`](#post-apiadmininvite-linkslink_idrevoke) | Switch off an invite link | browser session or API key, admins |
| POST | [`/api/admin/invite-links/{link_id}/switch-on`](#post-apiadmininvite-linkslink_idswitch-on) | Switch an invite link back on | browser session or API key, admins |
| POST | [`/api/bulk/admin/invite-links/delete`](#post-apibulkadmininvite-linksdelete) | Delete an invite link, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/invite-links/restore`](#post-apibulkadmininvite-linksrestore) | Undo deleting an invite link, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/invite-links/revoke`](#post-apibulkadmininvite-linksrevoke) | Switch off an invite link, for many at once | browser session or API key, admins |
| POST | [`/api/bulk/admin/invite-links/switch-on`](#post-apibulkadmininvite-linksswitch-on) | Switch an invite link back on, for many at once | browser session or API key, admins |
| POST | [`/api/join/claim`](#post-apijoinclaim) | Sign in as an existing account | anyone |
| POST | [`/api/join/create`](#post-apijoincreate) | Join as a new account | anyone |
| POST | [`/api/join/info`](#post-apijoininfo) | What an invite link is | anyone |
| POST | [`/api/join/match`](#post-apijoinmatch) | Accounts matching a name | anyone |

### GET /api/admin/invite-links

List invite links

Group invite links, a page at a time: label, places used and left, expiry, and whether each still works. The links themselves are never shown again after creation. next is the offset of the following page, or null on the last one.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_list_invite_links`](mcp.md#admin_list_invite_links) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |
| `offset` | query | integer | no | at least 0 | Rows to skip: the next value of the previous page. |
| `q` | query | string | no |  | Keep links whose label or maker contains this, in any case. |
| `sort` | query | string | no | one of `label`, `used`, `expires_at` | Field to sort the whole list by. Rows without it go last. |
| `dir` | query | string | no | one of `asc`, `desc` | Default asc. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `invite_links` | array of [`InviteLink`](#invitelink) | yes |  |  |
| `next` | integer or null | yes |  | Offset of the next page, or null on the last one. |
| `total` | integer | yes |  |  |

### POST /api/admin/invite-links

Create an invite link

One link for a group: each person who opens it joins as a new account with role (user, the default, or viewer), up to max_uses people, for days days.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_create_invite_link`](mcp.md#admin_create_invite_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `days` | integer | yes | 1 to 365 |  |
| `label` | string | yes | 1 to 80 characters |  |
| `max_uses` | integer | yes | 1 to 1000 |  |
| `role` | string | no | one of `user`, `viewer`; default `user` | The role each person who joins gets: user, or viewer (reads only). |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_by` | integer | yes |  |  |
| `created_by_name` | string | no |  |  |
| `expires_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `join_path` | string | yes |  | The link to hand out, shown in this response only. A credential: treat it like a password. |
| `label` | string | yes |  |  |
| `live` | boolean | yes |  |  |
| `max_uses` | integer | yes |  |  |
| `remaining` | integer | yes |  |  |
| `revoked` | boolean | yes |  |  |
| `role` | string | yes | one of `user`, `viewer` | The role each person who joins gets. |
| `used` | integer | yes |  |  |

### POST /api/admin/invite-links/{link_id}/delete

Delete an invite link

Take an invite link off the list and stop it working. The accounts it made stay.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_delete_invite_link`](mcp.md#admin_delete_invite_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/invite-links/{link_id}/limits

Change an invite link's places and expiry

Set how many people the link may take in (never fewer than have joined) and, when days is given, a new expiry counted from now. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_set_invite_link_limits`](mcp.md#admin_set_invite_link_limits) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `days` | integer or null | no | 1 to 365 | Counted from now. Leave out to keep the expiry. |
| `max_uses` | integer | yes | 1 to 1000 | Not fewer than have joined. |

**Reply 200**: Success

[`InviteLink`](#invitelink).

### POST /api/admin/invite-links/{link_id}/rename

Rename an invite link

Change the label people see on an invite link's join page (1-80 characters). expect, when given, is the label you think it has now.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_rename_invite_link`](mcp.md#admin_rename_invite_link) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | string or null | no |  | The label you think it has. Answers 409 if it has another. |
| `label` | string | yes | 1 to 80 characters | 1-80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `label` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

### POST /api/admin/invite-links/{link_id}/restore

Undo deleting an invite link

Bring back an invite link deleted in the last few minutes, working as before. The link then counts as this key's: revoking the key switches it off.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_restore_invite_link`](mcp.md#admin_restore_invite_link) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`InviteLink`](#invitelink).

### POST /api/admin/invite-links/{link_id}/revoke

Switch off an invite link

Stop an invite link from letting anyone else join or sign in through it. Accounts it already made keep working. Cannot be switched back on.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_invite_link`](mcp.md#admin_revoke_invite_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/admin/invite-links/{link_id}/switch-on

Switch an invite link back on

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_switch_on_invite_link`](mcp.md#admin_switch_on_invite_link) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `link_id` | path | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`InviteLink`](#invitelink).

### POST /api/bulk/admin/invite-links/delete

Delete an invite link, for many at once

Runs POST /api/admin/invite-links/{link_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_delete_invite_link_bulk`](mcp.md#admin_delete_invite_link_bulk) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/invite-links/restore

Undo deleting an invite link, for many at once

Runs POST /api/admin/invite-links/{link_id}/restore once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_restore_invite_link_bulk`](mcp.md#admin_restore_invite_link_bulk) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/invite-links/revoke

Switch off an invite link, for many at once

Runs POST /api/admin/invite-links/{link_id}/revoke once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_revoke_invite_link_bulk`](mcp.md#admin_revoke_invite_link_bulk) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/admin/invite-links/switch-on

Switch an invite link back on, for many at once

Runs POST /api/admin/invite-links/{link_id}/switch-on once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_switch_on_invite_link_bulk`](mcp.md#admin_switch_on_invite_link_bulk) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].link_id` | string | yes |  | The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/join/claim

Sign in as an existing account

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |
| `display_name` | string | no |  |  |
| `pin` | string | no |  |  |
| `user_id` | integer | no |  |  |

**Reply 200**: Success

[`Joined`](#joined).

### POST /api/join/create

Join as a new account

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |
| `display_name` | string | no |  |  |
| `pin` | string | no |  |  |
| `user_id` | integer | no |  |  |

**Reply 201**: Success

[`Joined`](#joined).

### POST /api/join/info

What an invite link is

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |
| `display_name` | string | no |  |  |
| `pin` | string | no |  |  |
| `user_id` | integer | no |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `label` | string | yes |  |  |
| `remaining` | integer | yes |  |  |

### POST /api/join/match

Accounts matching a name

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  |  |
| `display_name` | string | no |  |  |
| `pin` | string | no |  |  |
| `user_id` | integer | no |  |  |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `can_create` | boolean | yes |  |  |
| `matches` | array of object | yes |  |  |
| `matches[].display_name` | string | yes |  |  |
| `matches[].has_pin` | boolean | yes |  |  |
| `matches[].id` | integer | yes |  |  |

## Owner

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/owner/logs/days`](#get-apiownerlogsdays) | The days on record | browser session only, the owner |
| GET | [`/api/owner/logs/days/{date}`](#get-apiownerlogsdaysdate) | One day's entries | browser session only, the owner |
| POST | [`/api/owner/logs/days/{date}/delete`](#post-apiownerlogsdaysdatedelete) | Delete one day | browser session only, the owner |
| GET | [`/api/owner/logs/days/{date}/download`](#get-apiownerlogsdaysdatedownload) | One day's entries as a file | browser session only, the owner |
| POST | [`/api/owner/logs/prune`](#post-apiownerlogsprune) | Apply the retention rules now | browser session only, the owner |
| GET | [`/api/owner/logs/stream`](#get-apiownerlogsstream) | New log entries as they happen | browser session only, the owner |
| GET | [`/api/owner/portal`](#get-apiownerportal) | ProjectPortal's accounts | browser session only, the owner |
| POST | [`/api/owner/portal/connect`](#post-apiownerportalconnect) | Connect ProjectPortal | browser session only, the owner |
| POST | [`/api/owner/portal/disconnect`](#post-apiownerportaldisconnect) | Disconnect ProjectPortal | browser session only, the owner |
| GET | [`/api/owner/settings`](#get-apiownersettings) | config.yaml, as a form | browser session only, the owner |
| POST | [`/api/owner/settings`](#post-apiownersettings) | Save settings | browser session only, the owner |
| POST | [`/api/owner/users/{user_id}/password-access`](#post-apiownerusersuser_idpassword-access) | Allow or block an account's password | browser session only, the owner |

### GET /api/owner/logs/days

The days on record

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `q` | query | string | no |  | The Logs screen's search. |

**Reply 200**: Success

[`LogDays`](#logdays).

### GET /api/owner/logs/days/{date}

One day's entries

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |
| `q` | query | string | no |  | The Logs screen's search. |
| `before` | query | integer or null | no | at least 0 |  |
| `limit` | query | integer | no | 1 to 1000; default `200` | Rows to return. Default 200. |

**Reply 200**: Success

[`LogDay`](#logday).

### POST /api/owner/logs/days/{date}/delete

Delete one day

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### GET /api/owner/logs/days/{date}/download

One day's entries as a file

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `date` | path | string | yes |  | The day's date, from GET /api/owner/logs/days. |

**Reply 200**: Success

Text, as `application/x-ndjson`.

### POST /api/owner/logs/prune

Apply the retention rules now

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

[`PruneResult`](#pruneresult).

### GET /api/owner/logs/stream

New log entries as they happen

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `q` | query | string | no |  | The Logs screen's search. |

**Reply 200**: Success

Text, as `text/event-stream`.

### GET /api/owner/portal

ProjectPortal's accounts

The service accounts ProjectPortal works through, each with its live keys and when they expire.

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 404, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accounts` | array of [`PortalAccount`](#portalaccount) | yes |  | Every service account, oldest first. |

### POST /api/owner/portal/connect

Connect ProjectPortal

Makes the service account named name (ProjectPortal when left out) if there is none, and one admin key for it, lasting days (1-365), that may make keys for other accounts and never makes sign-in links. Answers with the key and its credential, shown only now: paste it into ProjectPortal as this app's admin key.

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `days` | integer | yes | 1 to 365 | How long the key lasts, in days. |
| `name` | string | no | 1 to 80 characters; default `ProjectPortal` | The service account's name. Left out: ProjectPortal. |

**Reply 201**: Success

[`NewAPIKey`](#newapikey).

### POST /api/owner/portal/disconnect

Disconnect ProjectPortal

Revokes every key of the service account user_id, and with them every key and link those keys made. The account stays, with no way in, until Connect gives it a key again.

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `user_id` | integer | yes |  | The service account. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `revoked` | integer | yes |  | Its keys revoked. The keys and links they made went with them. |

### GET /api/owner/settings

config.yaml, as a form

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 404, 429, 503 |

**Reply 200**: Success

[`SettingsSnapshot`](#settingssnapshot).

### POST /api/owner/settings

Save settings

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 409, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `changes` | object | yes |  | Setting paths and their new values. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `version` | string | yes |  |  |

**Reply 200**: Success

[`SettingsResult`](#settingsresult).

### POST /api/owner/users/{user_id}/password-access

Allow or block an account's password

|  |  |
|---|---|
| Who may call | browser session only, the owner |
| Errors | 400, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user_id` | path | integer | yes | at least 1 | The account's id, from GET /api/admin/users (admin_list_users over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `allowed` | boolean | yes |  |  |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |
| `password_blocked` | boolean | yes |  |  |

## Monitoring

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/api.json`](#get-apiapijson) | This document | browser session or API key, anyone signed in |
| GET | [`/api/api.md`](#get-apiapimd) | The API reference as Markdown tables for people | browser session or API key, anyone signed in |
| GET | [`/api/health`](#get-apihealth) | Is the process up | anyone |
| GET | [`/api/mcp.json`](#get-apimcpjson) | The MCP tools: every tool /mcp has, its arguments, and the route it stands for | browser session or API key, anyone signed in |
| GET | [`/api/mcp.md`](#get-apimcpmd) | The MCP tools as Markdown tables for people | browser session or API key, anyone signed in |
| GET | [`/api/ready`](#get-apiready) | Can the server do real work | anyone |
| GET | [`/mcp`](#get-mcp) | Refused: this server has no stream | anyone |
| POST | [`/mcp`](#post-mcp) | Model Context Protocol, at the key's role | API key only, anyone signed in |
| DELETE | [`/mcp`](#delete-mcp) | Refused: this server keeps no sessions | anyone |

### GET /api/api.json

This document

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The API reference itself; GET /api/mcp.json is the MCP one. |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

An empty object.

### GET /api/api.md

The API reference as Markdown tables for people

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The API reference itself, for people; GET /api/api.json is the same as JSON. |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

Text, as `text/markdown`.

### GET /api/health

Is the process up

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/mcp.json

The MCP tools: every tool /mcp has, its arguments, and the route it stands for

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The MCP reference itself; tools/list gives the same list. |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

An empty object.

### GET /api/mcp.md

The MCP tools as Markdown tables for people

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: The MCP reference itself, for people; tools/list gives the same list. |
| Errors | 401, 404, 429, 503 |

**Reply 200**: Success

Text, as `text/markdown`.

### GET /api/ready

Can the server do real work

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /mcp

Refused: this server has no stream

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 404, 429, 503 |

**Reply 405**: Success

### POST /mcp

Model Context Protocol, at the key's role

|  |  |
|---|---|
| Who may call | API key only, anyone signed in |
| MCP tool | None, HTTP only: The MCP endpoint itself. |
| Errors | 400, 401, 403, 404, 429, 503 |

**Request body**

An empty object.

**Reply 200**: Success

An empty object.

### DELETE /mcp

Refused: this server keeps no sessions

|  |  |
|---|---|
| Who may call | anyone |
| Errors | 404, 429, 503 |

**Reply 405**: Success

## Discover

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/discover`](#get-apidiscover) | Search Discover | browser session or API key, anyone signed in |
| POST | [`/api/discover/add`](#post-apidiscoveradd) | Add a Discover film | browser session or API key, anyone signed in |
| GET | [`/api/discover/facts`](#get-apidiscoverfacts) | Discover film details | browser session or API key, anyone signed in |
| GET | [`/api/discover/meta`](#get-apidiscovermeta) | Discover catalogue | browser session or API key, anyone signed in |
| POST | [`/api/discover/verdict`](#post-apidiscoververdict) | Skip a Discover film | browser session or API key, anyone signed in |

### GET /api/discover

Search Discover

The Wikipedia film catalogue, minus films the person skipped or watched unless asked for. Each film says whether it is already in the library (title_id) and the person's status on it. Answers total, films and, when nothing matched the exact words, fuzzy: true. q may be an IMDb title link or tt id, which finds that film whatever the other filters say. With q, title_hit says whether any catalogue film, filters aside, has those words in its title. Words the filters leave nothing for are searched again with the filters set aside: unfiltered: true.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`discover_search`](mcp.md#discover_search) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `q` | query | string | no |  | Words to find in the title, director or cast. |
| `from` | query | string | no |  | Earliest year. |
| `to` | query | string | no |  | Latest year. |
| `topic` | query | string | no |  | A topic id from GET /api/discover/meta. |
| `genre` | query | string | no |  | Genres, comma-separated. |
| `genremode` | query | string | no |  | all: every genre given. Default any. |
| `actor` | query | string | no |  | A cast member's name. |
| `only` | query | string | no |  | A source list id from GET /api/discover/meta. |
| `skipped` | query | string | no |  | hide, only or all: films skipped, here or as dropped in the library. Default hide. |
| `watched` | query | string | no |  | hide, only or all: films watched. Default hide. |
| `library` | query | string | no |  | hide: leave out films already in the library. Default all. |
| `rating` | query | string | no |  | Certifications to keep, comma-separated. |
| `norating` | query | string | no |  | Certifications to leave out, comma-separated. |
| `imdbfrom` | query | string | no |  | Lowest IMDb score, 0-10. |
| `imdbto` | query | string | no |  | Highest IMDb score, 0-10. |
| `votesfrom` | query | string | no |  | Fewest IMDb votes. |
| `votesto` | query | string | no |  | Most IMDb votes. |
| `runtimefrom` | query | string | no |  | Shortest running time, in minutes. |
| `runtimeto` | query | string | no |  | Longest running time, in minutes. |
| `sort` | query | string | no |  | notable, imdb, year, year-asc or title. Default notable. |
| `limit` | query | string | no |  | Films to return, at most 200. Default 60. |
| `offset` | query | string | no |  | Films to skip. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

An empty object.

### POST /api/discover/add

Add a Discover film

Add a film from Discover (the film object as it was given) to the library, with its Wikipedia details. status: watched for Seen it, or leave it out for no list. Refused with 409 possible_duplicate and the dupes unless force is true.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`discover_add`](mcp.md#discover_add) |
| Errors | 400, 401, 403, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `film` | object | yes |  | A film as GET /api/discover gives it. |
| `force` | boolean | no |  | Add it even if it looks like a title the library has. |
| `status` | string or null | no |  | watched for Seen it; leave out for no list. |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created` | boolean | yes |  |  |
| `state` | object | yes |  |  |
| `title` | object | yes |  |  |

### GET /api/discover/facts

Discover film details

Plot, cast and poster for up to 60 catalogue films, by article name (a film's url ends in it), keyed by article.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`discover_facts`](mcp.md#discover_facts) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `articles` | query | string | no |  | Wikipedia article names (a film's article), separated by \|. At most 60. |

**Reply 200**: Success

An empty object.

### GET /api/discover/meta

Discover catalogue

What the Discover catalogue holds: its source lists and topics, coverage, and rating counts.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`discover_meta`](mcp.md#discover_meta) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

An empty object.

### POST /api/discover/verdict

Skip a Discover film

Set the person's verdict on a film: skip hides it from them only, seen marks it seen, null clears it.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_verdict`](mcp.md#set_verdict) |
| Errors | 400, 401, 403, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `key` | string | yes |  | The film's key, from GET /api/discover. |
| `verdict` | string or null | no |  | skip (hide it from you), seen, or null to clear. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous` | string or null | yes |  | The verdict it replaced. |

## Jobs

| Method | Path | Summary | Who may call |
|---|---|---|---|
| GET | [`/api/jobs`](#get-apijobs) | Background jobs | browser session or API key, anyone signed in |
| POST | [`/api/jobs/{name}/start`](#post-apijobsnamestart) | Start a job | browser session or API key, admins |
| POST | [`/api/jobs/{name}/stop`](#post-apijobsnamestop) | Stop a job | browser session or API key, admins |

### GET /api/jobs

Background jobs

What the server is doing in the background (filling in titles, IMDb ratings, the catalogue), the poster cache, and whether lookups are on.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`jobs_status`](mcp.md#jobs_status) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `images` | object | yes |  | The poster cache. |
| `jobs` | array of object | yes |  | Each job's name, whether it runs by hand (manual), and what it is doing. |
| `network` | boolean | yes |  | providers.network: whether lookups are on. |

### POST /api/jobs/{name}/start

Start a job

Start a background job by its name (one marked manual). options are the job's own settings. Each job can make thousands of outbound calls.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_start_job`](mcp.md#admin_start_job) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `name` | path | string | yes |  | A job's name, from GET /api/jobs. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `options` | object | no |  | The job's own settings. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `job` | object | yes |  |  |
| `started` | boolean | yes |  |  |

### POST /api/jobs/{name}/stop

Stop a job

Ask a running background job to stop.

|  |  |
|---|---|
| Who may call | browser session or API key, admins |
| MCP tool | [`admin_stop_job`](mcp.md#admin_stop_job) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `name` | path | string | yes |  | A job's name, from GET /api/jobs. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `job` | object | yes |  |  |

## Library

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/bulk/merges/undo`](#post-apibulkmergesundo) | Undo a merge, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/sources/delete`](#post-apibulksourcesdelete) | Delete a source, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/sources/restore`](#post-apibulksourcesrestore) | Restore a source, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/titles/enrich`](#post-apibulktitlesenrich) | Fill a title in, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/titles/merge`](#post-apibulktitlesmerge) | Merge duplicates, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/titles/update`](#post-apibulktitlesupdate) | Edit a title, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/types/delete`](#post-apibulktypesdelete) | Delete a type, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/types/restore`](#post-apibulktypesrestore) | Restore a type, for many at once | browser session or API key, anyone signed in |
| GET | [`/api/dupes`](#get-apidupes) | Possible duplicates | browser session or API key, anyone signed in |
| POST | [`/api/dupes/dismiss`](#post-apidupesdismiss) | Not duplicates | browser session or API key, anyone signed in |
| POST | [`/api/dupes/undismiss`](#post-apidupesundismiss) | Undo not duplicates | browser session or API key, anyone signed in |
| GET | [`/api/export`](#get-apiexport) | Export the library | browser session or API key, anyone signed in |
| GET | [`/api/img/{key}`](#get-apiimgkey) | A poster | browser session or API key, anyone signed in |
| POST | [`/api/import/items`](#post-apiimportitems) | Import titles | browser session or API key, anyone signed in |
| POST | [`/api/import/parse`](#post-apiimportparse) | Read an import | browser session or API key, anyone signed in |
| POST | [`/api/import/{batch_id}/undo`](#post-apiimportbatch_idundo) | Undo an import | browser session or API key, anyone signed in |
| GET | [`/api/library`](#get-apilibrary) | The whole library | browser session or API key, anyone signed in |
| GET | [`/api/library/search`](#get-apilibrarysearch) | Search the library | browser session or API key, anyone signed in |
| POST | [`/api/merges/{merge_id}/undo`](#post-apimergesmerge_idundo) | Undo a merge | browser session or API key, anyone signed in |
| POST | [`/api/resolve`](#post-apiresolve) | Look titles up | browser session or API key, anyone signed in |
| GET | [`/api/sources`](#get-apisources) | Sources | browser session or API key, anyone signed in |
| POST | [`/api/sources`](#post-apisources) | Add a source | browser session or API key, anyone signed in |
| POST | [`/api/sources/{source_id}/delete`](#post-apisourcessource_iddelete) | Delete a source | browser session or API key, anyone signed in |
| POST | [`/api/sources/{source_id}/restore`](#post-apisourcessource_idrestore) | Restore a source | browser session or API key, anyone signed in |
| POST | [`/api/sources/{source_id}/update`](#post-apisourcessource_idupdate) | Change a source | browser session or API key, anyone signed in |
| POST | [`/api/state/bulk`](#post-apistatebulk) | Set state on many titles | browser session or API key, anyone signed in |
| POST | [`/api/state/{title_id}`](#post-apistatetitle_id) | Set status, rating or heart | browser session or API key, anyone signed in |
| POST | [`/api/titles`](#post-apititles) | Add a title | browser session or API key, anyone signed in |
| POST | [`/api/titles/bulk`](#post-apititlesbulk) | Change many titles | browser session or API key, anyone signed in |
| POST | [`/api/titles/check`](#post-apititlescheck) | Check for a duplicate | browser session or API key, anyone signed in |
| GET | [`/api/titles/{title_id}`](#get-apititlestitle_id) | Get a title | browser session or API key, anyone signed in |
| POST | [`/api/titles/{title_id}/delete`](#post-apititlestitle_iddelete) | Delete a title | browser session or API key, anyone signed in |
| POST | [`/api/titles/{title_id}/enrich`](#post-apititlestitle_idenrich) | Fill a title in | browser session or API key, anyone signed in |
| POST | [`/api/titles/{title_id}/merge`](#post-apititlestitle_idmerge) | Merge duplicates | browser session or API key, anyone signed in |
| POST | [`/api/titles/{title_id}/restore`](#post-apititlestitle_idrestore) | Restore a title | browser session or API key, anyone signed in |
| POST | [`/api/titles/{title_id}/update`](#post-apititlestitle_idupdate) | Edit a title | browser session or API key, anyone signed in |
| GET | [`/api/types`](#get-apitypes) | Media types | browser session or API key, anyone signed in |
| POST | [`/api/types`](#post-apitypes) | Add or change a type | browser session or API key, anyone signed in |
| POST | [`/api/types/{type_id}/delete`](#post-apitypestype_iddelete) | Delete a type | browser session or API key, anyone signed in |
| POST | [`/api/types/{type_id}/restore`](#post-apitypestype_idrestore) | Restore a type | browser session or API key, anyone signed in |
| GET | [`/api/vocab`](#get-apivocab) | Library vocabulary | browser session or API key, anyone signed in |

### POST /api/bulk/merges/undo

Undo a merge, for many at once

Runs POST /api/merges/{merge_id}/undo once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`undo_merge_bulk`](mcp.md#undo_merge_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].merge_id` | string | yes |  | From merging titles. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/sources/delete

Delete a source, for many at once

Runs POST /api/sources/{source_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_source_bulk`](mcp.md#delete_source_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].source_id` | string | yes |  | A source's id, from GET /api/sources. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/sources/restore

Restore a source, for many at once

Runs POST /api/sources/{source_id}/restore once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_source_bulk`](mcp.md#restore_source_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].source_id` | string | yes |  | A source's id, from GET /api/sources. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/titles/enrich

Fill a title in, for many at once

Runs POST /api/titles/{title_id}/enrich once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`enrich_title_bulk`](mcp.md#enrich_title_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].refresh` | boolean | no |  | Overwrite what is there, not just fill in what is missing. |
| `items[].title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.refresh` | boolean | no |  | Overwrite what is there, not just fill in what is missing. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/titles/merge

Merge duplicates, for many at once

Runs POST /api/titles/{title_id}/merge once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`merge_titles_bulk`](mcp.md#merge_titles_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].drop_ids` | array of string | no |  | Title ids, from GET /api/library (search_library over MCP). |
| `items[].title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.drop_ids` | array of string | no |  | Title ids, from GET /api/library (search_library over MCP). |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/titles/update

Edit a title, for many at once

Runs POST /api/titles/{title_id}/update once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`update_title_bulk`](mcp.md#update_title_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `items[].set` | object | no |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |
| `items[].title_id` | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `shared.set` | object | no |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/types/delete

Delete a type, for many at once

Runs POST /api/types/{type_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_type_bulk`](mcp.md#delete_type_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].reassign_to` | string or null | no |  | The type its titles move to. Needed while it holds any. |
| `items[].type_id` | string | yes |  | A type's id, from GET /api/types. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |
| `shared.reassign_to` | string or null | no |  | The type its titles move to. Needed while it holds any. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/types/restore

Restore a type, for many at once

Runs POST /api/types/{type_id}/restore once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_type_bulk`](mcp.md#restore_type_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].type_id` | string | yes |  | A type's id, from GET /api/types. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### GET /api/dupes

Possible duplicates

Groups of library titles that look like the same work, minus pairs marked as different.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_duplicates`](mcp.md#list_duplicates) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `groups` | array of object | yes |  | Each group: its ids, why they look alike, and the titles. |

### POST /api/dupes/dismiss

Not duplicates

Mark two or more titles as not the same, for the whole family. Returns the pairs, which undismissing takes back.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`dismiss_duplicates`](mcp.md#dismiss_duplicates) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `ids` | array of string | yes |  | Title ids, from GET /api/library (search_library over MCP). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `pairs` | array of string | yes |  | The pairs recorded: what undismissing takes back. |

### POST /api/dupes/undismiss

Undo not duplicates

Forget pairs that dismissing recorded.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`undismiss_duplicates`](mcp.md#undismiss_duplicates) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `pairs` | array of string | yes |  | Pairs from dismissing. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### GET /api/export

Export the library

The library with one person's state, as a JSON, CSV or Markdown outline download.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: a file download |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `format` | query | string | no | one of `json`, `csv`, `md`; default `json` | Default json. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

Raw bytes, as `application/octet-stream`.

### GET /api/img/{key}

A poster

A title's poster from the server's cache, fetched once if it is not there yet. Answers 304 to If-None-Match with its key.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: image bytes |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `key` | path | string | yes |  | A poster's key, from a title's poster path in GET /api/library. |

**Reply 200**: Success

Text, as `image/*`.

### POST /api/import/items

Import titles

Create titles from rows ({fields, state}, at most 200 per call), skipping any the library certainly has unless skip_dupes is false, and put them on the person's lists. Send the same batch_id for every call of one import; undoing the import takes the whole batch back.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`import_items`](mcp.md#import_items) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | string | no |  | The same for every call of one import, so it is undone as one. Default: a new one. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `rows` | array of object | yes |  | Up to 200 rows, each {fields, state}, as POST /api/import/parse gives them. |
| `skip_dupes` | boolean | no | default `true` | Skip rows the library certainly has. Default true. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `batch_id` | string | yes |  |  |
| `created` | integer | yes |  |  |
| `skipped` | integer | yes |  |  |

### POST /api/import/parse

Read an import

Read a pasted list or a file's text (format auto, outline, csv or json) into rows of title fields, each with its likeliest duplicate (dupe). Writes nothing: send the rows wanted to POST /api/import/items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`import_parse`](mcp.md#import_parse) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `format` | string | no | default `auto` | auto, outline, csv or json. Default auto. |
| `status` | string | no | default `queue` | The status rows without one get: queue, watching, watched or dropped. Default queue. |
| `text` | string | yes |  | A pasted list, or a file's text. |
| `type` | string | no | default `movie` | The type id titles without one get. Default movie. |

**Reply 200**: Success

An empty object.

### POST /api/import/{batch_id}/undo

Undo an import

Delete the titles one import created, and the importer's state on them.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`undo_import`](mcp.md#undo_import) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `batch_id` | path | string | yes |  | From POST /api/import/items. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `removed` | integer | yes |  | Titles taken back out. |

### GET /api/library

The whole library

Every title, the person's own state for each, who else in the family has watched or loved what, the types, the family's names, and IMDb scores. ?since= answers with only what changed.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | None, HTTP only: the whole library for the browser; search_library is the agent's version |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `since` | query | integer or null | no | at least 0 | A rev from an earlier answer: only what changed after it. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `full` | boolean | yes |  | false when only what changed since is here. |
| `genre_rules` | any | yes |  |  |
| `people` | array of object | yes |  |  |
| `rev` | integer | yes |  | The library's revision: send it back as since. |
| `scores` | object | yes |  | IMDb scores, by imdb id. |
| `social` | object | yes |  | Who else has watched or loved each title, by title id. |
| `states` | map of object | yes |  | The subject's state, by title id. |
| `subject` | integer | yes |  | Whose states these are. |
| `titles` | array of object | yes |  |  |
| `types` | array of object | yes |  |  |

### GET /api/library/search

Search the library

Titles in the family library, with the person's own state on each (status, rating, heart) and who else has watched or loved it. Every argument is optional.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`search_library`](mcp.md#search_library) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `text` | query | string | no | at most 200 characters | Words that must all appear in the title, director, cast, genres, tags or notes. |
| `type` | query | string | no |  | A type id such as movie or tv. |
| `status` | query | string | no |  | queue, watching, watched, dropped or none, or up_next for the Up next list (queue and watching, newest first). |
| `limit` | query | integer | no | 1 to 500; default `50` | Rows to return. Default 50. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `titles` | array of object | yes |  |  |
| `total` | integer | yes |  | How many titles matched, before limit. |

### POST /api/merges/{merge_id}/undo

Undo a merge

Put a merge back as it was: the dropped titles, and everyone's state and playlists.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`undo_merge`](mcp.md#undo_merge) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `merge_id` | path | string | yes |  | From merging titles. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/resolve

Look titles up

Identify names, names and years, or links with the configured providers, and say whether the library already has each. Writes nothing. Counts against the per-person lookup allowance (providers.lookups_per_minute); 503 lookups_off while the network is off.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`lookup`](mcp.md#lookup) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `kind` | string | no | default `any` | movie, tv, book, ... or any. |
| `lines` | array of string | yes |  | Up to 25 lines, each a name, a name and year, an IMDb id, or a link (IMDb, Wikipedia, TMDB, TVmaze...). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `results` | array of object | yes |  | One per line: the best candidates, whether the match is confident, and library titles it may duplicate. |

### GET /api/sources

Sources

The lists and pages titles were found on, newest first.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_sources`](mcp.md#list_sources) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

Array of object.

### POST /api/sources

Add a source

Remember a list or page titles were found on.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`create_source`](mcp.md#create_source) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `note` | string | no |  | Up to 2000 characters. |
| `tags` | array of string | no |  | Up to 20. |
| `title` | string | no |  | Up to 300 characters. |
| `url` | string | yes |  | An http(s) link. |

**Reply 201**: Success

An empty object.

### POST /api/sources/{source_id}/delete

Delete a source

Delete a source. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_source`](mcp.md#delete_source) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `source_id` | path | string | yes |  | A source's id, from GET /api/sources. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### POST /api/sources/{source_id}/restore

Restore a source

Bring back a deleted source, within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_source`](mcp.md#restore_source) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `source_id` | path | string | yes |  | A source's id, from GET /api/sources. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

An empty object.

### POST /api/sources/{source_id}/update

Change a source

Change a source's link, title, note or tags. Returns the previous values.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`update_source`](mcp.md#update_source) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `source_id` | path | string | yes |  | A source's id, from GET /api/sources. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `note` | string | no |  | Up to 2000 characters. |
| `tags` | array of string | no |  | Up to 20. |
| `title` | string | no |  | Up to 300 characters. |
| `url` | string | no |  | An http(s) link. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous` | object | yes |  | What the changed fields were before. |
| `source` | object | yes |  |  |

### POST /api/state/bulk

Set state on many titles

changes is {title id: {status, rating, heart, note, watched_at}}, up to 2000 titles: a bulk action sends the same change for every id. Returns each title's previous values, which sent back are the undo.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_states`](mcp.md#set_states) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `changes` | map of object | yes |  | {title id: {status, rating, heart, note, watched_at}}, up to 2000 titles. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous` | object | yes |  | Each title's previous values, by id: sent back, the undo. |

### POST /api/state/{title_id}

Set status, rating or heart

Change one person's state on a title: status (queue, watching, watched, dropped, or null for off the list), rating 1-10 or null, heart true/false, note, watched_at. Returns the previous values.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_state`](mcp.md#set_state) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `title_id` | path | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `set` | object | yes |  | A person's state: status (queue, watching, watched, dropped, or null), rating 1-10 or null, heart, note, watched_at. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous` | object | yes |  | What the changed fields were before: send them back to undo. |
| `state` | object | yes |  |  |

### POST /api/titles

Add a title

Add a title to the family library and put it on a person's list (state.status: queue by default). Refused with 409 possible_duplicate and the dupes it resembles unless force is true. Details are filled in in the background.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`add_title`](mcp.md#add_title) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `force` | boolean | no |  | Add it even if it looks like a title the library has. |
| `state` | object | no |  | A person's state: status (queue, watching, watched, dropped, or null), rating 1-10 or null, heart, note, watched_at. |
| `title` | object | yes |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |

**Reply 201**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created` | boolean | yes |  |  |
| `state` | object | yes |  |  |
| `title` | object | yes |  |  |

### POST /api/titles/bulk

Change many titles

One change to many titles at once. op: set_type (value: a type id), add_tags or remove_tags (value: a list of tags), delete, restore, or set_fields (value: {title id: fields}, the undo). Returns each title's previous values; send them back with set_fields to undo. Deletes are soft and restorable.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`bulk_edit_titles`](mcp.md#bulk_edit_titles) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `ids` | array of string | yes |  | Title ids, at most 2000. |
| `op` | string | yes | one of `set_type`, `add_tags`, `remove_tags`, `delete`, `restore`, `set_fields` | The change. |
| `value` | any | no |  | set_type: a type id. add_tags, remove_tags: a list of tags. set_fields: {title id: fields}, the undo. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous` | object | yes |  | Each changed title's previous values, by id: sent back with set_fields, the undo. |

### POST /api/titles/check

Check for a duplicate

Would adding this title make a duplicate? The library titles it resembles, with a score. Writes nothing.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`check_title`](mcp.md#check_title) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `title` | object | yes |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `matches` | array of object | yes |  | Library titles it resembles, each with its score and the title. |

### GET /api/titles/{title_id}

Get a title

Everything about one title, with the person's state on it (my_state) and who in the family has watched or loved it (family).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`get_title`](mcp.md#get_title) |
| Errors | 400, 401, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `title_id` | path | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

An empty object.

### POST /api/titles/{title_id}/delete

Delete a title

Take a title out of the library for everyone. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_title`](mcp.md#delete_title) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `title_id` | path | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `title` | object | yes |  |  |

### POST /api/titles/{title_id}/enrich

Fill a title in

Look the title up with the configured providers now and fill in missing details (refresh: true overwrites what is there). Returns the previous values.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`enrich_title`](mcp.md#enrich_title) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `title_id` | path | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `refresh` | boolean | no |  | Overwrite what is there, not just fill in what is missing. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous` | object | yes |  | What the changed fields were before. |
| `title` | object | yes |  |  |

### POST /api/titles/{title_id}/merge

Merge duplicates

Keep title_id and fold the drop_ids into it: everyone's state, playlists and details move over and the others are deleted. One undo step: undo the merge with the merge_id returned.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`merge_titles`](mcp.md#merge_titles) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `title_id` | path | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `drop_ids` | array of string | yes |  | Title ids, from GET /api/library (search_library over MCP). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `changed` | array of string | yes |  | The kept title's fields the merge filled in. |
| `merge_id` | string | yes |  | What undoing the merge takes. |
| `title` | object | yes |  |  |

### POST /api/titles/{title_id}/restore

Restore a title

Bring back a deleted title, within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_title`](mcp.md#restore_title) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `title_id` | path | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `title` | object | yes |  |  |

### POST /api/titles/{title_id}/update

Edit a title

Change shared details of a title (title, year, type, tags, notes, links, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url). Returns the previous values.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`update_title`](mcp.md#update_title) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `title_id` | path | string | yes |  | A title's id, from GET /api/library (search_library over MCP). |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `expect` | any | no |  | Optional: the rev you last read. If it changed meanwhile the call is refused with 409 changed_elsewhere and the current value. |
| `set` | object | yes |  | Title fields: title, year, type, tags, notes, genres, cast, creator, runtime, certification, imdb_id, wiki_url, poster_url. Unknown ones are ignored. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous` | object | yes |  | What the changed fields were before: send them back to undo. |
| `title` | object | yes |  |  |

### GET /api/types

Media types

The library's sections (Movies, TV, and any the family added), in order.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_types`](mcp.md#list_types) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

Array of object.

### POST /api/types

Add or change a type

Create a media type, or change one by its id. Movies and TV keep their lookup.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`save_type`](mcp.md#save_type) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `icon` | string | no |  |  |
| `id` | string | yes |  | a-z, 0-9 and -, up to 32; never changes once made. |
| `label` | string | yes |  | Up to 40 characters. |
| `lookup` | string | no | default `other` | What titles of this type are looked up as: movie, tv, book, ... or other. |
| `position` | integer or null | no |  |  |

**Reply 200**: Success

An empty object.

### POST /api/types/{type_id}/delete

Delete a type

Delete a media type. One that still holds titles needs reassign_to, the type they move to (409 type_in_use with their count otherwise). Movies and TV cannot be deleted. Soft: restoring it brings it back.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_type`](mcp.md#delete_type) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `type_id` | path | string | yes |  | A type's id, from GET /api/types. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `reassign_to` | string or null | no |  | The type its titles move to. Needed while it holds any. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `moved` | integer | yes |  | Titles moved to reassign_to. |

### POST /api/types/{type_id}/restore

Restore a type

Bring back a deleted media type, within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_type`](mcp.md#restore_type) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `type_id` | path | string | yes |  | A type's id, from GET /api/types. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

An empty object.

### GET /api/vocab

Library vocabulary

The fixed words: statuses, lookup kinds, and the canonical genre names.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`get_vocab`](mcp.md#get_vocab) |
| Errors | 401, 429, 503 |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `canonical_genres` | array of string | yes |  |  |
| `lookup_kinds` | array of string | yes |  |  |
| `statuses` | array of string | yes |  |  |

## Playlists

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/bulk/playlists/delete`](#post-apibulkplaylistsdelete) | Delete a playlist, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/playlists/restore`](#post-apibulkplaylistsrestore) | Restore a playlist, for many at once | browser session or API key, anyone signed in |
| GET | [`/api/playlists`](#get-apiplaylists) | Playlists | browser session or API key, anyone signed in |
| POST | [`/api/playlists`](#post-apiplaylists) | Create a playlist | browser session or API key, anyone signed in |
| POST | [`/api/playlists/reorder`](#post-apiplaylistsreorder) | Order playlists | browser session or API key, anyone signed in |
| POST | [`/api/playlists/{playlist_id}/add`](#post-apiplaylistsplaylist_idadd) | Add to a playlist | browser session or API key, anyone signed in |
| POST | [`/api/playlists/{playlist_id}/delete`](#post-apiplaylistsplaylist_iddelete) | Delete a playlist | browser session or API key, anyone signed in |
| POST | [`/api/playlists/{playlist_id}/move`](#post-apiplaylistsplaylist_idmove) | Move within a playlist | browser session or API key, anyone signed in |
| POST | [`/api/playlists/{playlist_id}/remove`](#post-apiplaylistsplaylist_idremove) | Remove from a playlist | browser session or API key, anyone signed in |
| POST | [`/api/playlists/{playlist_id}/restore`](#post-apiplaylistsplaylist_idrestore) | Restore a playlist | browser session or API key, anyone signed in |
| POST | [`/api/playlists/{playlist_id}/set`](#post-apiplaylistsplaylist_idset) | Set a playlist's titles | browser session or API key, anyone signed in |
| POST | [`/api/playlists/{playlist_id}/update`](#post-apiplaylistsplaylist_idupdate) | Rename a playlist | browser session or API key, anyone signed in |

### POST /api/bulk/playlists/delete

Delete a playlist, for many at once

Runs POST /api/playlists/{playlist_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_playlist_bulk`](mcp.md#delete_playlist_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/playlists/restore

Restore a playlist, for many at once

Runs POST /api/playlists/{playlist_id}/restore once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_playlist_bulk`](mcp.md#restore_playlist_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].playlist_id` | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### GET /api/playlists

Playlists

A person's playlists, in their order, each with its titles (items).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_playlists`](mcp.md#list_playlists) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `playlist_id` | query | integer or null | no | at least 1 | Over MCP only: that one playlist's titles, numbered in its order, instead of the list. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

Array of object.

### POST /api/playlists

Create a playlist

A new playlist, optionally with titles (items: title ids, in order).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`create_playlist`](mcp.md#create_playlist) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of string | no |  | Title ids, in order. |
| `name` | string | yes |  | Up to 80 characters. |

**Reply 201**: Success

An empty object.

### POST /api/playlists/reorder

Order playlists

Put the playlists in this order (ids: every playlist id, first to last).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`reorder_playlists`](mcp.md#reorder_playlists) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `ids` | array of integer | yes |  | Ids, first to last. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/playlists/{playlist_id}/add

Add to a playlist

Add titles at position (the end by default); the rest renumber. Returns the items before, which setting the items takes back.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`add_to_playlist`](mcp.md#add_to_playlist) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `playlist_id` | path | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `position` | integer or null | no | at least 1 | 1-based; the end by default. |
| `title_ids` | array of string | yes |  | Title ids, from GET /api/library (search_library over MCP). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist` | object | yes |  |  |
| `previous_items` | array of string | yes |  | The items before: what setting the items takes back. |

### POST /api/playlists/{playlist_id}/delete

Delete a playlist

Delete a playlist. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_playlist`](mcp.md#delete_playlist) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `playlist_id` | path | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### POST /api/playlists/{playlist_id}/move

Move within a playlist

Move one title to position; the rest renumber. Returns the items before, which setting the items takes back.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`move_in_playlist`](mcp.md#move_in_playlist) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `playlist_id` | path | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `position` | integer | yes | at least 1 | 1-based. |
| `title_id` | string | yes |  | The title to move. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist` | object | yes |  |  |
| `previous_items` | array of string | yes |  | The items before: what setting the items takes back. |

### POST /api/playlists/{playlist_id}/remove

Remove from a playlist

Take titles off a playlist; the rest renumber. Returns the items before, which setting the items takes back.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`remove_from_playlist`](mcp.md#remove_from_playlist) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `playlist_id` | path | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `title_ids` | array of string | yes |  | Title ids, from GET /api/library (search_library over MCP). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist` | object | yes |  |  |
| `previous_items` | array of string | yes |  | The items before: what setting the items takes back. |

### POST /api/playlists/{playlist_id}/restore

Restore a playlist

Bring back a deleted playlist, within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_playlist`](mcp.md#restore_playlist) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `playlist_id` | path | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist` | object | yes |  |  |

### POST /api/playlists/{playlist_id}/set

Set a playlist's titles

Replace a playlist's titles with items, in order: the undo of add, remove and move. Returns the items before.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_playlist_items`](mcp.md#set_playlist_items) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `playlist_id` | path | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of string | yes |  | Every title, in order. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist` | object | yes |  |  |
| `previous_items` | array of string | yes |  | The items before: what setting the items takes back. |

### POST /api/playlists/{playlist_id}/update

Rename a playlist

Give a playlist a new name. Returns the previous one.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`rename_playlist`](mcp.md#rename_playlist) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `playlist_id` | path | integer | yes | at least 1 | A playlist's id, from GET /api/playlists. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes |  | Up to 80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `playlist` | object | yes |  |  |
| `previous_name` | string | yes |  |  |

## Settings

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/bulk/views/delete`](#post-apibulkviewsdelete) | Delete a view, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/views/restore`](#post-apibulkviewsrestore) | Restore a view, for many at once | browser session or API key, anyone signed in |
| GET | [`/api/prefs`](#get-apiprefs) | Settings | browser session or API key, anyone signed in |
| POST | [`/api/prefs`](#post-apiprefs) | Change settings | browser session or API key, anyone signed in |
| GET | [`/api/views`](#get-apiviews) | Saved views | browser session or API key, anyone signed in |
| POST | [`/api/views`](#post-apiviews) | Save a view | browser session or API key, anyone signed in |
| POST | [`/api/views/reorder`](#post-apiviewsreorder) | Order views | browser session or API key, anyone signed in |
| POST | [`/api/views/{view_id}/delete`](#post-apiviewsview_iddelete) | Delete a view | browser session or API key, anyone signed in |
| POST | [`/api/views/{view_id}/restore`](#post-apiviewsview_idrestore) | Restore a view | browser session or API key, anyone signed in |
| POST | [`/api/views/{view_id}/update`](#post-apiviewsview_idupdate) | Change a view | browser session or API key, anyone signed in |

### POST /api/bulk/views/delete

Delete a view, for many at once

Runs POST /api/views/{view_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_view_bulk`](mcp.md#delete_view_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `items[].view_id` | integer | yes | at least 1 | A view's id, from GET /api/views. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/views/restore

Restore a view, for many at once

Runs POST /api/views/{view_id}/restore once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_view_bulk`](mcp.md#restore_view_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `items[].view_id` | integer | yes | at least 1 | A view's id, from GET /api/views. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### GET /api/prefs

Settings

A person's settings that follow them between devices: cards (layout per screen), last_query, default_view and ui.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`get_prefs`](mcp.md#get_prefs) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cards` | object | yes |  | How cards look, per screen. |
| `default_view` | object | yes |  |  |
| `last_query` | object | yes |  | The last query on each screen. |
| `ui` | object | yes |  |  |

### POST /api/prefs

Change settings

Change settings by section (cards, last_query, default_view, ui): each key given replaces that key within its section, and null removes it. Returns them all.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`save_prefs`](mcp.md#save_prefs) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cards` | object | no |  | Each key given replaces that key in the section; null removes it. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `default_view` | object | no |  | Each key given replaces that key in the section; null removes it. |
| `last_query` | object | no |  | Each key given replaces that key in the section; null removes it. |
| `ui` | object | no |  | Each key given replaces that key in the section; null removes it. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `cards` | object | yes |  | How cards look, per screen. |
| `default_view` | object | yes |  |  |
| `last_query` | object | yes |  | The last query on each screen. |
| `ui` | object | yes |  |  |

### GET /api/views

Saved views

A person's saved views: a named query on the library or Discover screen, in their order.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_views`](mcp.md#list_views) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

Array of object.

### POST /api/views

Save a view

Save a named view of a screen.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`create_view`](mcp.md#create_view) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `card` | object or null | no |  | How cards look in this view. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `icon` | string | no |  |  |
| `name` | string | yes |  | Up to 80 characters. |
| `query` | string | no |  | The screen's address, such as #library/all/queue?runtime=..100. |
| `scope` | string | no |  | The library section it is on. |
| `screen` | string | no |  | library or discover. |

**Reply 201**: Success

An empty object.

### POST /api/views/reorder

Order views

Put the saved views in this order (ids: view ids, first to last).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`reorder_views`](mcp.md#reorder_views) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `ids` | array of integer | yes |  | Ids, first to last. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/views/{view_id}/delete

Delete a view

Delete a saved view. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_view`](mcp.md#delete_view) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `view_id` | path | integer | yes | at least 1 | A view's id, from GET /api/views. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### POST /api/views/{view_id}/restore

Restore a view

Bring back a deleted saved view, within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_view`](mcp.md#restore_view) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `view_id` | path | integer | yes | at least 1 | A view's id, from GET /api/views. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `view` | object | yes |  |  |

### POST /api/views/{view_id}/update

Change a view

Change a saved view's name, query, card layout or icon. Returns the previous values.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`update_view`](mcp.md#update_view) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `view_id` | path | integer | yes | at least 1 | A view's id, from GET /api/views. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `card` | object or null | no |  | How cards look in this view. |
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `icon` | string | no |  |  |
| `name` | string | no |  |  |
| `query` | string | no |  | The screen's address, such as #library/all/queue?runtime=..100. |
| `scope` | string | no |  | The library section it is on. |
| `screen` | string | no |  | library or discover. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous` | object | yes |  | What the changed fields were before: send them back to undo. |
| `view` | object | yes |  |  |

## Suggestions

| Method | Path | Summary | Who may call |
|---|---|---|---|
| POST | [`/api/bulk/suggestions/delete`](#post-apibulksuggestionsdelete) | Delete a suggestion list, for many at once | browser session or API key, anyone signed in |
| POST | [`/api/bulk/suggestions/restore`](#post-apibulksuggestionsrestore) | Restore a suggestion list, for many at once | browser session or API key, anyone signed in |
| GET | [`/api/suggestions`](#get-apisuggestions) | Suggestion lists | browser session or API key, anyone signed in |
| POST | [`/api/suggestions`](#post-apisuggestions) | Create a suggestion list | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/reorder`](#post-apisuggestionsreorder) | Order suggestion lists | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/{list_id}/add`](#post-apisuggestionslist_idadd) | Add suggestions | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/{list_id}/delete`](#post-apisuggestionslist_iddelete) | Delete a suggestion list | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/{list_id}/move`](#post-apisuggestionslist_idmove) | Move a suggestion | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/{list_id}/note`](#post-apisuggestionslist_idnote) | Change a suggestion's note | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/{list_id}/remove`](#post-apisuggestionslist_idremove) | Remove suggestions | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/{list_id}/restore`](#post-apisuggestionslist_idrestore) | Restore a suggestion list | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/{list_id}/set`](#post-apisuggestionslist_idset) | Set a suggestion list's items | browser session or API key, anyone signed in |
| POST | [`/api/suggestions/{list_id}/update`](#post-apisuggestionslist_idupdate) | Rename a suggestion list | browser session or API key, anyone signed in |

### POST /api/bulk/suggestions/delete

Delete a suggestion list, for many at once

Runs POST /api/suggestions/{list_id}/delete once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_suggestion_list_bulk`](mcp.md#delete_suggestion_list_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### POST /api/bulk/suggestions/restore

Restore a suggestion list, for many at once

Runs POST /api/suggestions/{list_id}/restore once per item: items holds each one's id and fields, shared the fields they have in common (an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the reply says how each went. At most 100 items.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_suggestion_list_bulk`](mcp.md#restore_suggestion_list_bulk) |
| Errors | 400, 401, 403, 429, 503 |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | One entry per thing to change: its id, and any field that differs from shared. |
| `items[].list_id` | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `items[].user` | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |
| `shared` | object | no |  | Fields every item gets, unless the item sets its own. |

**Reply 200**: Success

[`BulkReply`](#bulkreply).

### GET /api/suggestions

Suggestion lists

A person's suggestion lists, in their order. Each item has its ref, note and added_at, the library title it is (title_id, or null for a Discover film not imported yet) and, for a Discover film, the film as GET /api/discover gives it.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`list_suggestions`](mcp.md#list_suggestions) |
| Errors | 400, 401, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | query | integer or null | no | at least 1 | Over MCP only: that one list's items, numbered in its order, instead of the lists. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Reply 200**: Success

Array of object.

### POST /api/suggestions

Create a suggestion list

A new, empty suggestion list. Fill it with add.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`create_suggestion_list`](mcp.md#create_suggestion_list) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes |  | Up to 80 characters. |

**Reply 201**: Success

An empty object.

### POST /api/suggestions/reorder

Order suggestion lists

Put the suggestion lists in this order (ids: every list id, first to last).

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`reorder_suggestion_lists`](mcp.md#reorder_suggestion_lists) |
| Errors | 400, 401, 403, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `ids` | array of integer | yes |  | Ids, first to last. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

### POST /api/suggestions/{list_id}/add

Add suggestions

Suggest Discover films (film_keys) and/or library titles (title_ids) at position (the end by default), each with the note given. One already in the list stays where it is, and takes the new note. A Discover film the library already has counts as that title. Returns the items before.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`add_suggestions`](mcp.md#add_suggestions) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | path | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `film_keys` | array of string | no |  | Discover film keys, from GET /api/discover (discover_search over MCP). |
| `note` | string | no | at most 200 characters | Why it is suggested, in a line: shown under the card. |
| `position` | integer or null | no | at least 1 | 1-based; the end by default. |
| `title_ids` | array of string | no |  | Library title ids, from GET /api/library (search_library over MCP). |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous_items` | array of object | yes |  | The items before: what setting the items takes back. |
| `suggestion_list` | object | yes |  |  |

### POST /api/suggestions/{list_id}/delete

Delete a suggestion list

Delete a suggestion list. Soft: restoring it brings it back within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`delete_suggestion_list`](mcp.md#delete_suggestion_list) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | path | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `deleted` | boolean | yes |  |  |

### POST /api/suggestions/{list_id}/move

Move a suggestion

Move one item to position; the rest renumber. Returns the items before.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`move_suggestion`](mcp.md#move_suggestion) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | path | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `position` | integer | yes | at least 1 | 1-based. |
| `ref` | string | yes |  | An item's ref: a title id, or cat:<film key>. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous_items` | array of object | yes |  | The items before: what setting the items takes back. |
| `suggestion_list` | object | yes |  |  |

### POST /api/suggestions/{list_id}/note

Change a suggestion's note

Replace one item's note (empty clears it). Returns the items before.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_suggestion_note`](mcp.md#set_suggestion_note) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | path | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `note` | string | yes | at most 200 characters | Why it is suggested, in a line: shown under the card. |
| `ref` | string | yes |  | An item's ref: a title id, or cat:<film key>. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous_items` | array of object | yes |  | The items before: what setting the items takes back. |
| `suggestion_list` | object | yes |  |  |

### POST /api/suggestions/{list_id}/remove

Remove suggestions

Take items off a suggestion list, by ref. Returns the items before.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`remove_suggestions`](mcp.md#remove_suggestions) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | path | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `refs` | array of string | yes |  | Item refs, as GET /api/suggestions gives them. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous_items` | array of object | yes |  | The items before: what setting the items takes back. |
| `suggestion_list` | object | yes |  |  |

### POST /api/suggestions/{list_id}/restore

Restore a suggestion list

Bring back a deleted suggestion list, within the undo window.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`restore_suggestion_list`](mcp.md#restore_suggestion_list) |
| Errors | 400, 401, 403, 404, 409, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | path | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `suggestion_list` | object | yes |  |  |

### POST /api/suggestions/{list_id}/set

Set a suggestion list's items

Replace a list's items, in order: the undo of add, remove, move and note. Returns the items before.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`set_suggestion_items`](mcp.md#set_suggestion_items) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | path | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `items` | array of object | yes |  | Every item ({ref, note, added_at}), in order. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous_items` | array of object | yes |  | The items before: what setting the items takes back. |
| `suggestion_list` | object | yes |  |  |

### POST /api/suggestions/{list_id}/update

Rename a suggestion list

Give a suggestion list a new name. Returns the previous one.

|  |  |
|---|---|
| Who may call | browser session or API key, anyone signed in |
| MCP tool | [`rename_suggestion_list`](mcp.md#rename_suggestion_list) |
| Errors | 400, 401, 403, 404, 429, 503 |

**Parameters**

| Name | In | Type | Required | Limits | Description |
|---|---|---|---|---|---|
| `list_id` | path | integer | yes | at least 1 | A suggestion list's id, from GET /api/suggestions. |
| `user` | query | integer or null | no | at least 1 | Whose lists: a user id, for an admin or someone given Showing. Default: your own. |

**Request body**

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `csrf_token` | string | no |  | From GET /api/me. Browser sessions only. |
| `name` | string | yes |  | Up to 80 characters. |

**Reply 200**: Success

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `previous_name` | string | yes |  |  |
| `suggestion_list` | object | yes |  |  |

## Schemas

The shapes the routes above refer to by name.

### APIKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `created_by` | integer | no |  | The admin who made this key for its owner. Absent if the owner made it. |
| `created_by_name` | string | no |  |  |
| `display_name` | string | no |  | The key's owner. On the admin list only. |
| `expired` | boolean | yes |  |  |
| `expires_at` | string (date-time) | no |  |  |
| `id` | string | yes |  |  |
| `last_used_at` | string (date-time) | no |  |  |
| `live` | boolean | yes |  |  |
| `may_mint_keys` | boolean | yes |  | Whether this key may make keys for other accounts. Only the owner switches it on. |
| `may_sign_in` | boolean | yes |  | Whether this key may make a login link for its own account. |
| `minted_by_key` | string | yes |  | The key that made this one, or empty. Revoking that key revokes this one. |
| `name` | string | yes |  |  |
| `revoked` | boolean | yes |  |  |
| `revoked_at` | string (date-time) | no |  |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `user_id` | integer | yes |  |  |

### BulkReply

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `done` | integer | yes |  | How many items worked. |
| `failed` | integer | yes |  | How many did not. |
| `results` | array of [`BulkResult`](#bulkresult) | yes |  | One per item, in the order they were sent. |

### BulkResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | string | no |  | When it failed: the route's words for why. |
| `index` | integer | yes |  | The item's place in items, from 0. |
| `ok` | boolean | yes |  |  |
| `reply` | object | no |  | When it worked: the route's own reply, if it has one. |
| `request_id` | string | no |  | On a 5xx: the reference that finds this failure in the log. |
| `status` | integer | no |  | When it failed: the status the route would have answered. |

### Error

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `code` | string | no | one of `not_authenticated`, `not_admin`, `view_only`, `session_only`, `owner_required`, `owner_protected`, `key_minting_off`, `service_account`, `not_found`, `invalid`, `conflict`, `rate_limited`, `forbidden` | On a 4xx: why, for a program to branch on (error is for a person). The list is closed. |
| `error` | string | yes |  |  |
| `field` | string | no |  | On a 400 about one field: its name. |
| `request_id` | string | no |  | On a 5xx: the reference that finds this failure in the log. |

### InviteLink

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_by` | integer | yes |  |  |
| `created_by_name` | string | no |  |  |
| `expires_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `label` | string | yes |  |  |
| `live` | boolean | yes |  |  |
| `max_uses` | integer | yes |  |  |
| `remaining` | integer | yes |  |  |
| `revoked` | boolean | yes |  |  |
| `role` | string | yes | one of `user`, `viewer` | The role each person who joins gets. |
| `used` | integer | yes |  |  |

### Joined

One of these:

1. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `ok` | boolean | yes |  |  |

2. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `challenge` | string | yes |  |  |
| `two_factor` | boolean | yes |  |  |

### LogDay

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `date` | string | yes |  |  |
| `entries` | array of object | yes |  |  |
| `next` | integer or null | yes |  |  |

### LogDays

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `days` | array of object | yes |  |  |
| `dropped` | integer | yes |  |  |
| `settings` | object | yes |  |  |
| `total_bytes` | integer | yes |  |  |

### LoginLink

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `expires_at` | string (date-time) or null | yes |  | null when it never expires. |
| `last_used_at` | string (date-time) or null | yes |  |  |
| `max_uses` | integer | yes |  | Sign-ins it allows. 0 when unlimited. |
| `unlimited` | boolean | yes |  |  |
| `uses` | integer | yes |  | Sign-ins so far. |

### Maintenance

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | string | yes |  |  |
| `maintenance` | string | yes | one of `read_only`, `full` |  |

### Me

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `account_role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `announcement` | string | yes |  | server.announcement. Empty when there is none. |
| `api_doc_url` | string | yes |  | Where to read the API reference as a page for people: config/api.md in app.repo, or /docs/api when there is no repo. |
| `api_key_id` | string | no |  | API keys only. |
| `api_key_name` | string | no |  | API keys only. |
| `api_keys_enabled` | boolean | yes |  |  |
| `auth` | string | yes |  |  |
| `authenticated` | boolean | yes |  |  |
| `can_show_others` | boolean | yes |  | Whether this caller may use the Showing picker. A user-scoped key of an admin reports what it may actually do, like role. |
| `capabilities` | array of string | yes |  | The optional parts of that contract this app has on now: viewer_role, account_expiry, key_minting, invite_links, key_sign_in, service_accounts, key_grants, error_codes, key_rotation, admin_sessions. |
| `contract` | integer | yes |  | Which version of the portal contract this app speaks: the Portal contract section of the webserver skills' SKILL.md. |
| `csrf_token` | string | no |  | Browser sessions only. |
| `default_subject` | integer or null | yes |  | Whose lists the Showing picker starts on: a user id, or null for your own. |
| `description` | string | yes |  | app.description. Empty when there is none. |
| `display_name` | string | yes |  |  |
| `has_password` | boolean | yes |  |  |
| `has_pin` | boolean | yes |  |  |
| `id` | integer | yes |  |  |
| `invite_links_enabled` | boolean | yes |  | Whether invite links are on. |
| `is_owner` | boolean | yes |  |  |
| `key` | [`MeKey`](#mekey) | no |  | API keys only: what this key may do. |
| `kind` | string | yes | one of `person`, `service` | person, or service for an account that only has API keys and is never signed into (ProjectPortal's own). |
| `login_link` | [`LoginLink`](#loginlink) or null | yes |  | Your own live login link, or null. |
| `logs_enabled` | boolean | yes |  |  |
| `logs_ui_clicks` | boolean | yes |  |  |
| `maintenance` | string | yes | one of `none`, `read_only`, `full` |  |
| `may_mint_keys` | boolean | no |  | API keys only: whether this key may make keys for other accounts. |
| `mcp_doc_url` | string | yes |  | Where to read the MCP tools as a page for people: config/mcp.md in app.repo, or /docs/mcp when there is no repo. |
| `mcp_enabled` | boolean | yes |  | server.mcp: whether POST /mcp answers. |
| `mcp_url` | string | yes |  | Where to read the MCP reference: config/mcp.json in app.repo, or /api/mcp.json when there is no repo. Only with server.mcp on. |
| `openapi_url` | string | yes |  | Where to read this API's reference: config/api.json in app.repo, or /api/api.json when there is no repo. |
| `owner` | boolean | yes |  | Whether this is the owner's account: the same as is_owner, under portal contract v3's name. |
| `password_blocked` | boolean | yes |  |  |
| `passwords_enabled` | boolean | yes |  |  |
| `repo` | string | yes |  | app.repo without a trailing / or .git: where the source lives. Empty when it is not set. |
| `role` | string | yes | one of `admin`, `user`, `viewer` | The effective role: never higher than an API key's own. A viewer may read, and change nothing. |
| `show_about` | boolean | yes |  | app.show_about: whether the menu has About. |
| `showing_locked` | boolean | yes |  | Whether an admin has locked the Showing picker. |
| `skill` | string | no |  | The webserver skill this app was scaffolded from (go-webserver or python-webserver), from its .skill-origin.yaml. Absent when that is not known. |
| `skill_commit` | string | no |  | The skill's commit this app was scaffolded from or last upgraded to, from its .skill-origin.yaml. Absent when that is not known. |
| `theme_id` | string | yes |  | The theme you use. Empty: the first. |
| `themes` | array of [`Theme`](#theme) or null | yes |  | Your themes (see the Theme schema): your own list, else the app's defaults, else null for the built-in ones. |
| `themes_builtins` | integer | yes |  | Which built-in themes that list has seen (see builtins on POST /api/account/themes). |
| `themes_custom` | boolean | yes |  | Whether you have your own list rather than following the defaults. |
| `two_factor` | boolean | yes |  |  |
| `two_factor_enabled` | boolean | yes |  |  |
| `username` | string | yes |  |  |
| `version` | string | yes |  | The running build. dev when none was stamped. |

### MeKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `expires_at` | string (date-time) | no |  | When the key stops working. Absent when it never does. |
| `id` | string | yes |  |  |
| `may_mint_keys` | boolean | yes |  | Whether this key may make keys for other accounts. |
| `may_sign_in` | boolean | yes |  | Whether this key may make a login link for its own account. |
| `name` | string | yes |  |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` | The key's own role. The role it acts with is the lower of this and the account's. |

### Member

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `id` | integer | yes |  |  |

### NewAPIKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `created_by` | integer | no |  | The admin who made this key for its owner. Absent if the owner made it. |
| `created_by_name` | string | no |  |  |
| `credential` | string | yes |  | Shown in this response only, and never recoverable. |
| `display_name` | string | no |  | The key's owner. On the admin list only. |
| `expired` | boolean | yes |  |  |
| `expires_at` | string (date-time) | no |  |  |
| `id` | string | yes |  |  |
| `last_used_at` | string (date-time) | no |  |  |
| `live` | boolean | yes |  |  |
| `may_mint_keys` | boolean | yes |  | Whether this key may make keys for other accounts. Only the owner switches it on. |
| `may_sign_in` | boolean | yes |  | Whether this key may make a login link for its own account. |
| `minted_by_key` | string | yes |  | The key that made this one, or empty. Revoking that key revokes this one. |
| `name` | string | yes |  |  |
| `revoked` | boolean | yes |  |  |
| `revoked_at` | string (date-time) | no |  |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `user_id` | integer | yes |  |  |

### PortalAccount

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `display_name` | string | yes |  |  |
| `id` | integer | yes |  |  |
| `keys` | array of [`APIKey`](#apikey) | yes |  | Its live keys, newest first. |

### PruneResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `bytes_after` | integer | yes |  |  |
| `bytes_before` | integer | yes |  |  |
| `compressed` | integer | yes |  |  |
| `deleted` | integer | yes |  |  |

### Revoked

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `api_keys` | integer | yes |  |  |
| `login_links` | integer | yes |  |  |
| `passwords` | integer | yes |  |  |
| `sessions` | integer | yes |  |  |

### RotatedKey

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `credential` | string | yes |  | The key's new credential, shown in this response only. The old one stopped working. |

### Session

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `created_at` | string (date-time) | yes |  |  |
| `current` | boolean | yes |  |  |
| `expires_at` | string (date-time) | yes |  |  |
| `id` | string | yes |  |  |
| `ip` | string | no |  |  |
| `label` | string | no |  | The name you gave this device. |
| `last_seen_at` | string (date-time) | no |  |  |
| `user_agent` | string | no |  |  |

### SettingsResult

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `applied` | array of string or null | yes |  |  |
| `changes` | array of object or null | yes |  |  |
| `restart` | array of string or null | yes |  |  |
| `scripts` | array of string or null | yes |  |  |
| `unchanged` | array of string or null | yes |  |  |
| `version` | string | yes |  |  |

### SettingsSnapshot

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `error` | object or null | yes |  |  |
| `error.at` | string (date-time) | yes |  |  |
| `error.message` | string | yes |  |  |
| `error.origin` | string | yes |  |  |
| `file` | string | yes |  |  |
| `in_container` | boolean | yes |  |  |
| `secret_file` | string | yes |  |  |
| `sections` | array of object | yes |  |  |
| `sections[].help` | string | yes |  |  |
| `sections[].keys` | array of object | yes |  |  |
| `sections[].keys[].apply` | string | yes |  |  |
| `sections[].keys[].default` | any | yes |  |  |
| `sections[].keys[].file_only` | boolean | yes |  | A path: change it in config.yaml, never here. |
| `sections[].keys[].help` | string | yes |  |  |
| `sections[].keys[].in_file` | boolean | yes |  |  |
| `sections[].keys[].key` | string | yes |  |  |
| `sections[].keys[].locked` | boolean | yes |  |  |
| `sections[].keys[].name` | string | yes |  |  |
| `sections[].keys[].pending_restart` | boolean | yes |  |  |
| `sections[].keys[].running` | any | yes |  |  |
| `sections[].keys[].type` | string | yes |  |  |
| `sections[].keys[].value` | any | yes |  |  |
| `sections[].name` | string | yes |  |  |
| `stale` | boolean | yes |  |  |
| `version` | string | yes |  | Send it back when saving: a changed file is refused with a 409. |
| `writable` | boolean | yes |  |  |

### SignIn

One of these:

1. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `ok` | boolean | yes |  |  |

2. An object:

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `challenge` | string | yes |  |  |
| `two_factor` | boolean | yes |  |  |

### Theme

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `accent` | string | yes |  | The main color: what you can press. |
| `background` | string | no |  | The page. Left out: the mode's own. |
| `button` | object or null | no |  | How the theme's buttons look. A choice left out is the default (rounded, normal, raised, normal). |
| `button.case` | string | no | one of `normal`, `upper` |  |
| `button.depth` | string | no | one of `flat`, `raised`, `glossy` |  |
| `button.shape` | string | no | one of `square`, `soft`, `rounded`, `pill` |  |
| `button.weight` | string | no | one of `normal`, `medium`, `bold` |  |
| `dark` | object or null | no |  | A light theme's colors for dark mode, kept while it is light. Switching the theme to dark swaps them in. A light theme's light (or a dark theme's dark) is dropped. |
| `dark.accent` | string | yes |  | The main color: what you can press. |
| `dark.background` | string | no |  | The page. Left out: the mode's own. |
| `dark.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `dark.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `dark.surface` | string | no |  | Cards. Left out: the mode's own. |
| `id` | string | yes |  | Lower-case letters, digits, - and _, up to 32. |
| `light` | object or null | no |  | A dark theme's colors for light mode, kept while it is dark. Switching the theme to light swaps them in. |
| `light.accent` | string | yes |  | The main color: what you can press. |
| `light.background` | string | no |  | The page. Left out: the mode's own. |
| `light.overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `light.second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `light.surface` | string | no |  | Cards. Left out: the mode's own. |
| `mode` | string | yes | one of `light`, `dark` |  |
| `name` | string | yes |  | 1 to 60 characters. |
| `overrides` | map of string | no |  | Worked-out colors replaced by name: text, accent, accentFg, accentText, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, rowOdd and rowEven (alternating table rows), and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back. |
| `second` | string | yes |  | Says where you are: active nav item, headings, info. |
| `surface` | string | no |  | Cards. Left out: the mode's own. |

### User

| Field | Type | Required | Limits | Description |
|---|---|---|---|---|
| `can_show_others` | boolean | yes |  | Whether this account has the Showing picker (admins always do). |
| `created_at` | string (date-time) | yes |  |  |
| `default_subject` | integer or null | yes |  | Whose lists it starts on: a user id, or null for its own. |
| `disabled` | boolean | yes |  | Switched off, or its expiry has passed. |
| `display_name` | string | yes |  |  |
| `expired` | boolean | yes |  | Whether expires_at has passed. |
| `expires_at` | string (date-time) or null | yes |  | When the account stops working, or null for never. |
| `has_password` | boolean | yes |  |  |
| `id` | integer | yes |  |  |
| `kind` | string | yes | one of `person`, `service` | person, or service for an account with API keys only (ProjectPortal's own). |
| `login_link` | [`LoginLink`](#loginlink) or null | yes |  | The account's live login link, or null. |
| `owner` | boolean | yes |  |  |
| `password_blocked` | boolean | yes |  |  |
| `role` | string | yes | one of `admin`, `user`, `viewer` |  |
| `showing_locked` | boolean | yes |  | Whether an admin has fixed whose lists it sees. |
| `two_factor` | boolean | yes |  |  |
| `username` | string | yes |  | Empty until a password is set. |
