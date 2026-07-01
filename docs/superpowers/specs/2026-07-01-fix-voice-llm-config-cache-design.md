# Design Spec: Fix Voice LLM Configuration and Device Binding Cache Delay

## 1. Problem Description

During voice testing or device connection, the user encounters an error: `LLM 未配置：请在 /admin 用户页为该绑定用户点击「配置 LLM」填写 API Key`, even though the device/user has already been correctly bound or configured. 

There are two root causes:
1. **API Key Wiping Bug**: On the `/admin` user page, clicking "Configure LLM" and submitting updates (e.g., updating the model name) with the API Key field left blank (since the hint says "configured, leave empty to keep unchanged") sends `api_key: ""` to `/admin/api/users`. In `upsert_user`, `_merge_dict` merges `api_key: ""` over the existing key in the database, effectively deleting it.
2. **5-Minute Cache Delay Bug**: `VoicePostgresRepository` caches successful and failed device authentication results in an in-memory dictionary `self._auth_cache` for 300 seconds (5 minutes). When a device is newly bound, unbound, or its user's LLM config is updated, this cache is not invalidated. Reconnection attempts within 5 minutes retrieve the stale configuration.

## 2. Proposed Changes

We will modify [postgres_repository.py](file:///home/peter/huada/project/Interesting/codex_agent/shuxin/src/shuxin/voice/postgres_repository.py) to:
1. Prevent `upsert_user` from merging empty `api_key` values from payload overrides over existing database values.
2. Introduce a helper method `_clear_auth_cache(self, device_id: str | None = None)` to invalidate cache entries.
3. Invoke `_clear_auth_cache` upon user updates (`upsert_user`), device binding (`_bind_device_for_user`, `admin_bind_device`), and device unbinding (`_unbind_active_device`).

---

## 3. Detailed Implementation Plan

### 3.1. Add `_clear_auth_cache` Helper
Add the following method to `VoicePostgresRepository`:
```python
    def _clear_auth_cache(self, device_id: str | None = None) -> None:
        """Clear device hello authentication cache to prevent stale configuration."""
        if not hasattr(self, "_auth_cache"):
            return
        if device_id:
            self._auth_cache.pop(device_id, None)
        else:
            self._auth_cache.clear()
```

### 3.2. Fix `upsert_user` Key Wiping
Modify `upsert_user` in `postgres_repository.py`:
```python
        llm_config = dict(payload.get("llm_config") or {})
        if not llm_config.get("api_key"):
            llm_config.pop("api_key", None)
            existing_llm = existing_row["llm_config"] if existing_row else None
            llm_config = _merge_dict(_json_obj(existing_llm), llm_config)
```
Also, at the end of `upsert_user`, clear the entire cache:
```python
        self._clear_auth_cache()
```

### 3.3. Clear Cache on Binding/Unbinding Changes
1. In `_bind_device_for_user`:
   ```python
   self._clear_auth_cache(device_id)
   ```
2. In `admin_bind_device`:
   ```python
   self._clear_auth_cache(selected_device)
   ```
3. In `_unbind_active_device`:
   ```python
   self._clear_auth_cache(device_id)
   ```

---

## 4. Verification Plan

1. **Verify API Key Wiping**:
   - Manually save a user's configuration through the admin API or form with an empty `api_key` in the payload. Check the database `users` table to confirm that the existing API key was NOT deleted or overwritten by `""`.
2. **Verify Cache Invalidation**:
   - Bind a device, fetch it (triggers cache), update the user's config, and authenticate again. Verify that the changes take effect immediately without a 5-minute wait.
   - Run existing unit tests (`pytest tests/`) to ensure no regressions in user and device management APIs.
