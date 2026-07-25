import { request } from "../../../core/http";
import { requireSession } from "../../../core/auth";

export async function fetchUserProfile() {
  const session_token = requireSession();
  return request("/api/users/me", {
    method: "POST",
    data: { session_token },
  });
}

export async function fetchMyDevices() {
  const session_token = requireSession();
  return request("/api/devices/my", {
    method: "POST",
    data: { session_token },
  });
}

export async function fetchUploadToken(purpose = "ugc_avatar") {
  const session_token = requireSession();
  return request("/api/users/upload-token", {
    method: "POST",
    data: { session_token, purpose },
  });
}

export async function updateUserProfile(payload: {
  nickname?: string;
  avatar_key?: string;
}) {
  const session_token = requireSession();
  return request("/api/users/profile", {
    method: "POST",
    data: { session_token, ...payload },
  });
}

export async function clearUserAvatar() {
  const session_token = requireSession();
  return request("/api/users/avatar/clear", {
    method: "POST",
    data: { session_token },
  });
}

/** Upload local file path to Qiniu using token from fetchUploadToken. */
export function uploadFileToQiniu(opts: {
  filePath: string;
  token: string;
  key: string;
  uploadUrl: string;
}): Promise<void> {
  const uploadUrl = String(opts.uploadUrl || "").replace(/\/?$/, "/");
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: uploadUrl,
      filePath: opts.filePath,
      name: "file",
      formData: {
        token: opts.token,
        key: opts.key,
      },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve();
          return;
        }
        reject(new Error(`upload failed: HTTP ${res.statusCode}`));
      },
      fail: (err) => reject(new Error(err.errMsg || "upload failed")),
    });
  });
}
