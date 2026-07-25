import { computed, ref } from "vue";
import { clearSession, isLoggedIn, storedUserId } from "../../../core/auth";
import { formatPointsLabel } from "../../../utils/companion-points";
import {
  clearUserAvatar,
  fetchMyDevices,
  fetchUploadToken,
  fetchUserProfile,
  updateUserProfile,
  uploadFileToQiniu,
} from "../api/user";

export function useProfile() {
  const loading = ref(false);
  const saving = ref(false);
  const message = ref("");
  const userId = ref("");
  const deviceCount = ref(0);
  const factoryQa = ref(false);
  const remainYuan = ref<number | null>(null);
  const quotaConfigured = ref(false);
  const quotaExhausted = ref(false);
  const nickname = ref("");
  const avatarUrl = ref("");
  const avatarKey = ref("");
  const lastSavedNickname = ref("");
  const avatarMenuVisible = ref(false);

  const loggedIn = computed(() => isLoggedIn());
  const displayUserId = computed(
    () => userId.value || storedUserId() || "未登录"
  );
  const displayName = computed(
    () => nickname.value.trim() || displayUserId.value
  );
  const balanceLabel = computed(() => {
    if (!quotaConfigured.value) return "—";
    if (remainYuan.value == null) return "查询失败";
    return formatPointsLabel(remainYuan.value);
  });
  const hasCustomAvatar = computed(() => Boolean(avatarUrl.value || avatarKey.value));

  async function loadProfile() {
    loading.value = true;
    message.value = "";
    try {
      const [me, devices] = await Promise.all([fetchUserProfile(), fetchMyDevices()]);
      userId.value = me.user_id || storedUserId();
      factoryQa.value = Boolean(me.roles?.factory_qa);
      nickname.value = String(me.nickname || "");
      lastSavedNickname.value = nickname.value;
      avatarUrl.value = String(me.avatar_url || "");
      avatarKey.value = String(me.avatar_key || "");
      const quota = me.quota || {};
      deviceCount.value = (devices.items || []).length;
      quotaConfigured.value = Boolean(quota.configured);
      quotaExhausted.value = Boolean(quota.exhausted);
      remainYuan.value = quota.remain_yuan == null ? null : Number(quota.remain_yuan);
      if (quotaExhausted.value && quota.message) {
        message.value = quota.message;
      }
    } catch (error: any) {
      message.value = error.message || String(error);
    } finally {
      loading.value = false;
    }
  }

  async function saveNickname(opts?: { silent?: boolean }) {
    const next = nickname.value.trim();
    if (next === lastSavedNickname.value.trim()) return;
    if (next && next.length > 32) {
      uni.showToast({ title: "昵称最多 32 字", icon: "none" });
      return;
    }
    saving.value = true;
    message.value = "";
    try {
      const me: any = await updateUserProfile({ nickname: next });
      nickname.value = String(me.nickname || "");
      lastSavedNickname.value = nickname.value;
      if (!opts?.silent) {
        uni.showToast({ title: "昵称已保存", icon: "success" });
      }
    } catch (error: any) {
      message.value = error.message || String(error);
      uni.showToast({ title: message.value || "保存失败", icon: "none" });
    } finally {
      saving.value = false;
    }
  }

  function onNicknameInput(e: any) {
    nickname.value = String(e?.detail?.value ?? "");
  }

  function onNicknameBlur(e?: any) {
    const fromEvent = e?.detail?.value;
    if (fromEvent != null && String(fromEvent).length > 0) {
      nickname.value = String(fromEvent);
    }
    void saveNickname({ silent: true });
  }

  function onNicknameChange(e: any) {
    const v = String(e?.detail?.value ?? "").trim();
    if (!v) return;
    nickname.value = v;
    void saveNickname({ silent: true });
  }

  function formatAvatarError(error: any): string {
    const raw = String(error?.message || error || "");
    const lower = raw.toLowerCase();
    if (
      lower.includes("not declared") ||
      raw.includes("未声明") ||
      lower.includes("privacy agreement") ||
      lower.includes("api scope")
    ) {
      return "请在公众平台隐私指引中声明昵称头像后再测";
    }
    return raw || "上传失败";
  }

  async function uploadAvatarFromPath(filePath: string) {
    if (!filePath) return;
    saving.value = true;
    message.value = "";
    try {
      let localPath = filePath;
      // 微信头像常返回 https 临时链，需先下载再 uploadFile
      if (/^https?:\/\//i.test(filePath)) {
        localPath = await new Promise<string>((resolve, reject) => {
          uni.downloadFile({
            url: filePath,
            success: (res) => {
              if (res.statusCode >= 200 && res.statusCode < 300 && res.tempFilePath) {
                resolve(res.tempFilePath);
                return;
              }
              reject(new Error("下载头像失败"));
            },
            fail: (err) => reject(new Error(err.errMsg || "下载头像失败")),
          });
        });
      }
      const tokenRes: any = await fetchUploadToken("ugc_avatar");
      const token = String(tokenRes.token || "");
      const key = String(tokenRes.key || "");
      const uploadUrl = String(tokenRes.upload_url || "");
      if (!token || !key || !uploadUrl) {
        throw new Error("上传凭证不完整");
      }
      await uploadFileToQiniu({ filePath: localPath, token, key, uploadUrl });
      const me: any = await updateUserProfile({ avatar_key: key });
      avatarUrl.value = String(me.avatar_url || "");
      avatarKey.value = String(me.avatar_key || "");
      uni.showToast({ title: "头像已更新", icon: "success" });
    } catch (error: any) {
      const tip = formatAvatarError(error);
      message.value = tip;
      uni.showToast({ title: tip, icon: "none", duration: 3500 });
    } finally {
      saving.value = false;
    }
  }

  function onChooseAvatar(e: any) {
    const path = String(e?.detail?.avatarUrl || e?.detail?.avatar_url || "").trim();
    if (!path) {
      const errMsg = String(e?.detail?.errMsg || e?.errMsg || "");
      const tip = formatAvatarError({ message: errMsg || "未获取到头像，请重试" });
      uni.showToast({ title: tip, icon: "none", duration: 3500 });
      return;
    }
    avatarMenuVisible.value = false;
    void uploadAvatarFromPath(path);
  }

  function pickFromAlbum() {
    avatarMenuVisible.value = false;
    uni.chooseImage({
      count: 1,
      sizeType: ["compressed"],
      sourceType: ["album", "camera"],
      success: (res) => {
        const path = (res.tempFilePaths || [])[0];
        if (path) void uploadAvatarFromPath(path);
      },
      fail: (err) => {
        const tip = formatAvatarError({ message: err?.errMsg || "选择图片失败" });
        uni.showToast({ title: tip, icon: "none", duration: 3500 });
      },
    });
  }

  function showAvatarMenu() {
    if (saving.value) return;
    avatarMenuVisible.value = true;
  }

  function closeAvatarMenu() {
    avatarMenuVisible.value = false;
  }

  async function restoreDefaultAvatar() {
    if (!hasCustomAvatar.value) {
      uni.showToast({ title: "当前已是默认头像", icon: "none" });
      closeAvatarMenu();
      return;
    }
    closeAvatarMenu();
    saving.value = true;
    message.value = "";
    try {
      const me: any = await clearUserAvatar();
      avatarUrl.value = String(me.avatar_url || "");
      avatarKey.value = String(me.avatar_key || "");
      uni.showToast({ title: "已恢复默认", icon: "success" });
    } catch (error: any) {
      message.value = error.message || String(error);
      uni.showToast({ title: message.value || "操作失败", icon: "none" });
    } finally {
      saving.value = false;
    }
  }

  function logout() {
    clearSession();
    uni.redirectTo({ url: "/pages/login/login" });
  }

  function copyUserId() {
    const value = displayUserId.value;
    if (!value || value === "未登录") return;
    uni.setClipboardData({
      data: value,
      success: () => uni.showToast({ title: "已复制", icon: "success" }),
    });
  }

  return {
    loading,
    saving,
    message,
    userId,
    deviceCount,
    factoryQa,
    remainYuan,
    quotaConfigured,
    quotaExhausted,
    nickname,
    avatarUrl,
    avatarKey,
    hasCustomAvatar,
    avatarMenuVisible,
    loggedIn,
    displayUserId,
    displayName,
    balanceLabel,
    loadProfile,
    saveNickname,
    onNicknameInput,
    onNicknameBlur,
    onNicknameChange,
    pickFromAlbum,
    onChooseAvatar,
    restoreDefaultAvatar,
    showAvatarMenu,
    closeAvatarMenu,
    logout,
    copyUserId,
  };
}
