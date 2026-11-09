import { computed, ref } from "vue";
import { clearSession, isLoggedIn, storedUserId } from "../../../core/auth";
import { fetchMyDevices, fetchUserProfile } from "../api/user";

export function useProfile() {
  const loading = ref(false);
  const message = ref("");
  const userId = ref("");
  const deviceCount = ref(0);
  const factoryQa = ref(false);
  const remainYuan = ref<number | null>(null);
  const quotaConfigured = ref(false);
  const quotaExhausted = ref(false);

  const loggedIn = computed(() => isLoggedIn());
  const displayUserId = computed(
    () => userId.value || storedUserId() || "未登录"
  );
  const balanceLabel = computed(() => {
    if (!quotaConfigured.value) return "—";
    if (remainYuan.value == null) return "查询失败";
    return `${remainYuan.value} 分钟`;
  });

  async function loadProfile() {
    loading.value = true;
    message.value = "";
    try {
      const [me, devices] = await Promise.all([fetchUserProfile(), fetchMyDevices()]);
      userId.value = me.user_id || storedUserId();
      factoryQa.value = Boolean(me.roles?.factory_qa);
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
    message,
    userId,
    deviceCount,
    factoryQa,
    remainYuan,
    quotaConfigured,
    quotaExhausted,
    loggedIn,
    displayUserId,
    balanceLabel,
    loadProfile,
    logout,
    copyUserId,
  };
}
