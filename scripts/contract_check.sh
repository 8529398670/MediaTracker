#!/usr/bin/env bash
# Check a running app against ProjectPortal's contract, reading only.
#
#   scripts/contract_check.sh <base_url> < key_file
#   pbpaste | scripts/contract_check.sh https://app.example.com
#
# The API key is read from stdin, never from the command line, so it stays out
# of shell history and the process list. Every call is a GET: /api/health,
# /api/me, /api/admin/users?limit=1, and, when the app lists key_grants and
# the key may make keys, the keys of the first account that is not an admin's;
# when it lists admin_sessions, that account's signed-in devices.
#
# Prints one PASS, WARN or FAIL line per part of the contract, naming the
# refusal's code on a failure. Exits 1 when any part failed. Needs curl.
set -euo pipefail

case "${1:-}" in
	-h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
	"") sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2 ;;
esac
base="${1%/}"
command -v curl >/dev/null 2>&1 || { echo "ERROR: needs curl" >&2; exit 2; }

key=""
IFS= read -r key || true
key="$( printf '%s' "$key" | tr -d '[:space:]' )"
[ -n "$key" ] || { echo "ERROR: no API key on stdin" >&2; exit 2; }

failed=0
pass() { printf 'PASS  %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failed=1; }

# get PATH [auth] sets body and status. The key goes to curl on stdin, as a
# config line, so it never appears in curl's arguments either.
body="" status=""
get() {
	local out
	if [ "${2:-auth}" = "auth" ]; then
		out="$( printf 'header = "Authorization: Bearer %s"\n' "$key" | curl -sS -K - -w '\n%{http_code}' "$base$1" 2>/dev/null )" || out=$'\n000'
	else
		out="$( curl -sS -w '\n%{http_code}' "$base$1" 2>/dev/null )" || out=$'\n000'
	fi
	status="${out##*$'\n'}"
	body="${out%$'\n'*}"
}

# field NAME [TEXT] is the first value of "NAME": in the JSON, unquoted. Good
# enough for the flat values read here, with no jq to depend on.
field() {
	printf '%s' "${2-$body}" | tr -d '\n' | tr ',{' '\n\n' | grep -m 1 "^[[:space:]]*\"$1\":" | sed -E 's/^[^:]*:[[:space:]]*//; s/[]}[:space:]]*$//; s/^"//; s/"$//' || true
}

# why is what a refusal said: its code, or the status alone.
why() {
	local code
	code="$( field code )"
	if [ -n "$code" ]; then printf '%s (%s)' "$status" "$code"; else printf '%s' "$status"; fi
}

listed() { printf '%s' "$capabilities" | grep -q "\"$1\""; }

# Health: the up/down check, no key.
get /api/health anon
if [ "$status" = "200" ]; then pass "health: up"; else fail "health: $( why )"; fi

# Who the key is, and what it may do.
get /api/me
if [ "$status" != "200" ]; then
	fail "me: $( why ) -- the key was refused"
	exit 1
fi
me="$body"
contract="$( field contract )"
capabilities="$( printf '%s' "$me" | tr -d '\n' | sed -n 's/.*"capabilities":[[:space:]]*\[\([^]]*\)\].*/\1/p' )"
pass "me: $( field display_name ) (contract ${contract:-1}, capabilities ${capabilities:-none})"
role="$( field role )"
if [ "$role" = "admin" ]; then pass "role: admin"; else fail "role: the key acts as ${role:-nobody}, the portal needs admin"; fi
case "$( field owner )" in
	true) warn "owner: this is the owner's own key -- it works, but give the portal an account of its own" ;;
	false) pass "owner: an account of the portal's own" ;;
esac
if [ "$( field kind )" = "service" ]; then pass "kind: a service account"; fi
if [ "${contract:-1}" -lt 3 ]; then warn "contract: v${contract:-1}, the app needs the webserver-upgrade skill for v3"; fi
if listed error_codes; then pass "error codes: every refusal names its code"; else warn "error codes: refusals carry no code"; fi

mints=""
if listed key_grants; then
	key_part="$( printf '%s' "$me" | tr -d '\n' | sed -n 's/.*"key":[[:space:]]*{\([^}]*\)}.*/\1/p' )"
	mints="$( field may_mint_keys "$key_part" )"
	if [ "$mints" = "true" ]; then pass "key: may make keys"; else fail "key: may not make keys (key_minting_off) -- use Connect on the owner's API keys screen"; fi
	expires="$( field expires_at "$key_part" )"
	if [ -z "$expires" ]; then
		pass "key: never expires"
	else
		stamp="${expires:0:19}"
		then_s="$( date -u -d "$stamp" +%s 2>/dev/null || date -u -j -f '%Y-%m-%dT%H:%M:%S' "$stamp" +%s 2>/dev/null || echo "" )"
		if [ -n "$then_s" ]; then
			days=$(( ( then_s - $( date -u +%s ) ) / 86400 ))
			if [ "$days" -lt 30 ]; then warn "key: expires in $days days ($expires)"; else pass "key: expires in $days days"; fi
		else
			pass "key: expires $expires"
		fi
	fi
fi

# The accounts list.
get '/api/admin/users?limit=1'
if [ "$status" = "200" ]; then pass "accounts: listed"; else fail "accounts: $( why )"; fi

# The first account that is not an admin's: the one the reads below look at.
# Only the owner reads another admin's, and the portal is not the owner.
target="" target_read=""
first_target() {
	if [ -z "$target_read" ]; then
		target_read=1
		get '/api/admin/users?limit=200'
		# One account per line: a row ends at its first }, after the fields read here.
		target="$( printf '%s' "$body" | tr -d '\n' | tr '}' '\n' | grep '"owner":false' | grep -v '"role":"admin"' | head -n 1 | sed -n 's/.*"id":\([0-9][0-9]*\).*/\1/p' || true )"
	fi
}

# One account's keys, the minting routes' read.
if [ "$mints" = "true" ]; then
	first_target
	if [ -z "$target" ]; then
		warn "keys: no account but admins' to read"
	else
		get "/api/admin/users/$target/keys"
		if [ "$status" = "200" ]; then pass "keys: account $target's keys listed"; else fail "keys: account $target: $( why )"; fi
	fi
fi

# One account's signed-in devices, for matching people across apps.
if listed admin_sessions; then
	first_target
	if [ -z "$target" ]; then
		warn "sessions: no account but admins' to read"
	else
		get "/api/admin/users/$target/sessions"
		if [ "$status" != "200" ]; then
			fail "sessions: account $target: $( why )"
		elif printf '%s' "$body" | grep -q '"id"' && ! printf '%s' "$body" | grep -q '"ip"'; then
			warn "sessions: account $target's devices listed, without addresses -- only the owner and a service account see them"
		else
			pass "sessions: account $target's devices listed"
		fi
	fi
fi

exit "$failed"
