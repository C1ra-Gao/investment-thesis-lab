"""Read exactly the user-authorized macOS item; never log subprocess output."""

import os
import subprocess

SERVICE = "thesislab-deepseek-api"


class KeychainAccessFailure(ValueError):
    pass


def read_authorized_key():
    account = os.environ.get("USER")
    if not account:raise KeychainAccessFailure("current_macOS_account_unknown")
    try:
        result = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", SERVICE,
                                 "-a", account, "-w"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=8)
    except subprocess.TimeoutExpired:
        raise KeychainAccessFailure("keychain_access_timeout_or_dialog_pause") from None
    except OSError:
        raise KeychainAccessFailure("keychain_command_unavailable") from None
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").lower()
        code = "keychain_item_not_found" if "could not be found" in detail else (
            "keychain_interaction_required_pause" if "interaction is not allowed" in detail else "keychain_access_denied")
        raise KeychainAccessFailure(code)
    try:key = result.stdout.decode("utf-8").rstrip("\r\n")
    except UnicodeError:raise KeychainAccessFailure("keychain_secret_encoding_invalid") from None
    if not key:raise KeychainAccessFailure("keychain_secret_empty")
    return key
