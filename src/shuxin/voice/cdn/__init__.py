"""CDN helpers (Qiniu Kodo + Fusion domain)."""

from shuxin.voice.cdn.purposes import get_purpose, resolve_key
from shuxin.voice.cdn.qiniu import public_url, public_url_with_version, qiniu_config
from shuxin.voice.cdn.qiniu_delete import delete_object, delete_user_avatar
from shuxin.voice.cdn.token_signer import issue_upload_token

__all__ = [
    "public_url",
    "public_url_with_version",
    "qiniu_config",
    "get_purpose",
    "resolve_key",
    "issue_upload_token",
    "delete_object",
    "delete_user_avatar",
]
