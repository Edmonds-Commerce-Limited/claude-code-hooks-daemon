#!/bin/bash
# release_tag_verify.sh - is a release tag signed by a key the project trusts?
# (Plan 00625, the relayed ruling in DESIGN 11a, items 2 and 3, review M1.)
#
# Sourced, never executed. Defines one function:
#
#   release_tag_verify <daemon_dir> <tag> <signers_file>
#
# Returns 0 when <tag> may be installed unattended, 1 otherwise, and sets two
# globals (it prints nothing):
#   RELEASE_TAG_VERIFY_SHA     the verified tag OBJECT sha (empty on refusal)
#   RELEASE_TAG_VERIFY_REASON  one-line reason for a refusal (empty on success)
#
# This signature is a CROSS-VERSION CONTRACT: a newer upgrade.sh sources the
# copy in the INSTALLED clone, which may be older. Never change the arguments
# or the two globals; add a new function instead.
#
# A tag is trusted only when ALL of these hold:
#   - its name is a plain release tag, vX.Y.Z;
#   - <signers_file> exists, holds at least one key line, and its physical
#     path is not inside <daemon_dir> (a key fetched with the tag proves nothing);
#   - ssh-keygen is available;
#   - origin publishes refs/tags/<tag> (M1: a tag only in the local clone is
#     never installed), and after fetching it the local tag is that object;
#   - the object is an annotated tag whose own header names <tag> (a signed
#     tag replayed under a newer name is refused);
#   - it carries an SSH signature (a GPG one could verify against whatever
#     keyring the user has, so it is refused) that verifies against
#     <signers_file>, with every git config override in the environment
#     removed and gpg.program forced to fail.
#
# Side effects: unsets GIT_CONFIG_PARAMETERS, GIT_CONFIG_COUNT and every
# GIT_CONFIG_KEY_*/GIT_CONFIG_VALUE_* in the calling shell, and force-fetches
# the one tag into <daemon_dir>.

# Exported because the caller, not this file, reads them.
export RELEASE_TAG_VERIFY_SHA=""
export RELEASE_TAG_VERIFY_REASON=""

# _rtv_physical <path> - the physical absolute path of <path> (symlinks
# resolved); fails when it does not exist.
_rtv_physical() {
    local _dir _base _target
    if [ -d "$1" ]; then
        (cd -P -- "$1" && pwd -P)
        return
    fi
    _dir="$(dirname -- "$1")"
    _base="$(basename -- "$1")"
    _dir="$(cd -P -- "$_dir" && pwd -P)" || return 1
    if [ -L "$_dir/$_base" ]; then
        _target="$(readlink -- "$_dir/$_base")" || return 1
        case "$_target" in
            /*) ;;
            *) _target="$_dir/$_target" ;;
        esac
        _rtv_physical "$_target"
        return
    fi
    [ -e "$_dir/$_base" ] || return 1
    printf '%s/%s\n' "$_dir" "$_base"
}

_rtv_refuse() {
    RELEASE_TAG_VERIFY_SHA=""
    RELEASE_TAG_VERIFY_REASON="$1"
    return 1
}

release_tag_verify() {
    local _daemon_dir="$1" _tag="$2" _signers="$3"
    local _name _ssh_keygen _signers_phys _daemon_phys _remote _remote_sha _local_sha
    local _header _line _body _verify_out
    RELEASE_TAG_VERIFY_SHA=""
    RELEASE_TAG_VERIFY_REASON=""

    unset GIT_CONFIG_PARAMETERS GIT_CONFIG_COUNT
    for _name in "${!GIT_CONFIG_KEY_@}" "${!GIT_CONFIG_VALUE_@}"; do
        unset "$_name"
    done

    if ! [[ "$_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        _rtv_refuse "$(printf '%q' "$_tag") is not a release tag (vX.Y.Z)"
        return 1
    fi

    if [ ! -f "$_signers" ] || ! grep -qEv '^[[:space:]]*(#|$)' "$_signers"; then
        _rtv_refuse "no trusted release-signing key in $_signers"
        return 1
    fi
    if ! _signers_phys="$(_rtv_physical "$_signers")" || ! _daemon_phys="$(_rtv_physical "$_daemon_dir")"; then
        _rtv_refuse "the signers file or the daemon clone cannot be resolved"
        return 1
    fi
    case "$_signers_phys" in
        "$_daemon_phys"/*)
            _rtv_refuse "the signers file $_signers is inside the daemon clone, so it proves nothing about the clone's tags"
            return 1
            ;;
    esac

    if ! _ssh_keygen="$(command -v ssh-keygen)"; then
        _rtv_refuse "ssh-keygen is not installed, so the release signature cannot be checked"
        return 1
    fi

    if ! _remote="$(git -C "$_daemon_dir" ls-remote --tags --refs origin "refs/tags/$_tag")"; then
        _rtv_refuse "origin could not be asked for $_tag"
        return 1
    fi
    _remote_sha=""
    while IFS=$'\t' read -r _line _name; do
        if [ "$_name" = "refs/tags/$_tag" ]; then
            _remote_sha="$_line"
        fi
    done <<< "$_remote"
    if [ -z "$_remote_sha" ]; then
        _rtv_refuse "$_tag is not on origin"
        return 1
    fi
    if ! git -C "$_daemon_dir" fetch -q --no-tags --force origin "+refs/tags/$_tag:refs/tags/$_tag"; then
        _rtv_refuse "$_tag could not be fetched from origin"
        return 1
    fi
    _local_sha="$(git -C "$_daemon_dir" rev-parse --verify -q "refs/tags/$_tag")" || _local_sha=""
    if [ "$_local_sha" != "$_remote_sha" ]; then
        _rtv_refuse "the fetched $_tag is not the object origin publishes"
        return 1
    fi

    if [ "$(git -C "$_daemon_dir" cat-file -t "$_remote_sha")" != "tag" ]; then
        _rtv_refuse "$_tag is not an annotated tag, so it carries no signature"
        return 1
    fi
    if ! _body="$(git -C "$_daemon_dir" cat-file tag "$_remote_sha")"; then
        _rtv_refuse "the $_tag tag object cannot be read"
        return 1
    fi
    _header=""
    while IFS= read -r _line; do
        [ -z "$_line" ] && break
        case "$_line" in
            "tag "*) _header="${_line#tag }" ;;
        esac
    done <<< "$_body"
    if [ "$_header" != "$_tag" ]; then
        _rtv_refuse "the tag object published as $_tag names ${_header:-no tag}"
        return 1
    fi
    case "$_body" in
        *"-----BEGIN SSH SIGNATURE-----"*) ;;
        *)
            _rtv_refuse "$_tag carries no SSH signature"
            return 1
            ;;
    esac

    if ! _verify_out="$(git -C "$_daemon_dir" \
        -c gpg.ssh.allowedSignersFile="$_signers_phys" \
        -c gpg.ssh.program="$_ssh_keygen" \
        -c gpg.program=false \
        -c gpg.x509.program=false \
        verify-tag "$_remote_sha" 2>&1)"; then
        _rtv_refuse "the signature on $_tag does not verify against a key in $_signers ($(printf '%s' "$_verify_out" | tr '\n' ' '))"
        return 1
    fi

    RELEASE_TAG_VERIFY_SHA="$_remote_sha"
    return 0
}
