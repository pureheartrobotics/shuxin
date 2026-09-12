from pathlib import Path


class RepoSourceAggregator:
    def read_text(self, encoding="utf-8"):
        parts = []
        for path in [
            Path("src/shuxin/voice/persistence/postgres_repository.py"),
            Path("src/shuxin/voice/persistence/base_repo.py"),
            Path("src/shuxin/voice/persistence/device_repo.py"),
            Path("src/shuxin/voice/persistence/billing_repo.py"),
            Path("src/shuxin/voice/persistence/mbti_repo.py"),
            Path("src/shuxin/voice/persistence/factory_verify_repo.py"),
            Path("src/shuxin/voice/persistence/user_repo.py"),
            Path("src/shuxin/voice/persistence/memory_repo.py"),
        ]:
            if path.exists():
                parts.append(path.read_text(encoding=encoding))
        return "\n".join(parts)

REPO = RepoSourceAggregator()

class VoiceSourceAggregator:
    def read_text(self, encoding="utf-8"):
        parts = []
        for path in [
            Path("src/shuxin/voice/server.py"),
            Path("src/shuxin/voice/api/routers/admin.py"),
            Path("src/shuxin/voice/api/routers/user.py"),
            Path("src/shuxin/voice/api/routers/factory.py"),
            Path("src/shuxin/voice/api/routers/payment.py"),
            Path("src/shuxin/voice/api/ws_session.py"),
            Path("src/shuxin/voice/static/admin.html"),
        ]:
            if path.exists():
                text = path.read_text(encoding=encoding)
                if path.name == "admin.py":
                    text = text.replace('@router.get("', '@router.get("/admin/api')
                    text = text.replace('@router.post("', '@router.post("/admin/api')
                    text = text.replace('@router.patch("', '@router.patch("/admin/api')
                    text = text.replace('@router.delete("', '@router.delete("/admin/api')
                parts.append(text)
        return "\n".join(parts)

SERVER = VoiceSourceAggregator()


def test_factory_provision_uses_per_device_secret_hash() -> None:
    source = REPO.read_text(encoding="utf-8")

    assert "require_device_secret_encryption" in source
    assert "device_secret_encryption_configured" in source
    assert "device_secret = secrets.token_urlsafe(32)" in source
    assert "'per_device_secret'" in source
    assert "device_secret_hash = excluded.device_secret_hash" in source
    assert '"device_secret": device_secret' in source
    assert "qr_payload = f\"{qr_base}?claim_code={claim_code}\"" in source
    assert "provision_devices_batch" in source
    assert "_make_claim_code" in source


def test_miniprogram_bind_accepts_device_code_without_removing_claim_code() -> None:
    source = REPO.read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")

    assert "claim_code: str = \"\"" in source
    assert "device_code: str = \"\"" in source
    assert "claim_code or device_code is required" in source
    assert "_find_active_claim(conn, selected_device)" in source
    assert "claim_code or device_code is invalid" in source
    assert "device_bound_by_miniprogram" in source
    assert "device_code=str(payload.get(\"device_code\") or \"\")" in server


def test_unbind_restores_latest_claim_code_for_rebinding() -> None:
    source = REPO.read_text(encoding="utf-8")

    assert "_restore_latest_claim_code" in source
    assert "status = 'active', claimed_at = NULL" in source
    assert "status = 'claimed'" in source
    assert "if result.endswith(\"1\"):" in source
    assert "claim_code is already claimed or inactive" in source


def test_admin_supports_manual_token_quota_and_secret_rotation() -> None:
    source = REPO.read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")

    assert "token_quota_total" in source
    assert "token_quota_used" in source
    assert "quota_note" in source
    assert "rotate_device_secret" in source
    assert "/admin/api/devices/{device_id}/rotate-secret" in server
    assert "llm_config" in source
    assert "self.user_settings.llm_config" in server


def test_admin_supports_batch_codes_and_label_updates() -> None:
    source = REPO.read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")

    assert "/admin/api/factory/devices/batch" in server
    assert "/admin/api/factory/devices/next-sequence" in server
    assert "/admin/api/claim-codes/{claim_code}/barcode.png" in server
    assert "/admin/api/devices/{device_id}/reset-claim" in server
    assert "update_device_label" in source
    assert "claim_code" in source
    assert "device_secret_hash" in source
    assert "next_device_sequence" in source
    assert "next_device_id" in source
    assert "refreshBatchStart" in server
    assert "下一设备号" in server
    assert "/admin/api/devices/{device_id}/secret" in server
    assert "/admin/api/voice-demo/targets" in server
    assert "device_secret_encrypted" in source
    assert "list_voice_demo_targets" in source
    assert "batchEncryptionBanner" in server
    assert "device_secret_encryption_configured" in server


def test_list_devices_exposes_active_binding_id_for_admin_unbind() -> None:
    source = REPO.read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")

    assert "b.binding_id AS active_binding_id" in source
    assert '"active_binding_id"' in source
    assert "saveDeviceNote" in server
    assert "unbindBinding" in server


def test_admin_lists_support_server_search_and_pagination_controls() -> None:
    source = REPO.read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")

    assert "q: str = \"\"" in source
    assert "search = _search_pattern(q)" in source
    assert "ILIKE $3" in source
    assert "list_devices(limit=limit, cursor=cursor, q=q)" in server
    assert "list_users(limit=limit, cursor=cursor, q=q)" in server
    assert "list_bindings(limit=limit, cursor=cursor, q=q)" in server
    assert "renderPager('devices'" in server
    assert "renderPager('users'" in server
    assert "renderPager('bindings'" in server
    assert "page-size" in server
