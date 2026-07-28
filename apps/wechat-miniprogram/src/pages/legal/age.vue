<template>
  <view class="page">
    <view class="hero">
      <text class="brand">初心</text>
      <text class="title">年满 18 岁确认</text>
      <text class="lead">开始与伙伴对话前，请确认你已年满十八周岁。</text>
    </view>

    <scroll-view scroll-y class="body">
      <view class="card">
        <text class="p">
          本产品面向年满 18 周岁的成年人提供陪伴对话服务。未满 18
          周岁的用户请在监护人指导下使用，或停止使用本服务。
        </text>
        <text class="p">
          点击确认即表示：你声明自己年满 18 周岁，并理解陪伴对话内容仅供参考，不能替代专业医疗、法律或心理咨询。
        </text>
        <text class="p muted">协议版本：{{ version }}</text>
      </view>
    </scroll-view>

    <view class="footer">
      <label class="check-row" @tap="checked = !checked">
        <checkbox :checked="checked" color="#2f604f" @tap.stop="checked = !checked" />
        <text class="check-label">我已年满 18 周岁，并同意上述说明</text>
      </label>
      <button class="confirm" :disabled="!checked || busy" @tap="onConfirm">确认并继续</button>
      <button class="cancel" size="mini" @tap="onCancel">暂不使用</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onLoad } from "@dcloudio/uni-app";
import { AGE_POLICY_VERSION, markAgeAgreed } from "../../utils/policy";
import { postAgeConsent } from "../../modules/companions/api";

const version = AGE_POLICY_VERSION;
const checked = ref(false);
const busy = ref(false);
const returnUrl = ref("");

onLoad((query: any) => {
  returnUrl.value = decodeURIComponent(String(query?.return_url || ""));
});

async function onConfirm() {
  if (!checked.value || busy.value) return;
  busy.value = true;
  try {
    await postAgeConsent(AGE_POLICY_VERSION);
    markAgeAgreed();
    if (returnUrl.value) {
      uni.redirectTo({ url: returnUrl.value });
    } else {
      uni.navigateBack({ fail: () => uni.switchTab({ url: "/pages/partners/partners" }) });
    }
  } catch (e: any) {
    uni.showToast({ title: e?.message || "提交失败", icon: "none" });
  } finally {
    busy.value = false;
  }
}

function onCancel() {
  uni.navigateBack({ fail: () => uni.switchTab({ url: "/pages/partners/partners" }) });
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(165deg, #f3ebe1 0%, #e8efe9 55%, #f7f4ef 100%);
  padding: 48rpx 40rpx 40rpx;
  box-sizing: border-box;
}
.hero {
  margin-bottom: 32rpx;
}
.brand {
  display: block;
  font-size: 28rpx;
  letter-spacing: 0.35em;
  color: #6f665b;
  font-weight: 600;
}
.title {
  display: block;
  margin-top: 16rpx;
  font-size: 48rpx;
  font-weight: 700;
  color: #24211c;
}
.lead {
  display: block;
  margin-top: 12rpx;
  font-size: 28rpx;
  line-height: 1.5;
  color: #6f665b;
}
.body {
  flex: 1;
  height: 0;
}
.card {
  padding: 36rpx 32rpx;
  border-radius: 24rpx;
  background: rgba(255, 252, 246, 0.92);
  border: 1rpx solid rgba(210, 200, 186, 0.85);
}
.p {
  display: block;
  font-size: 28rpx;
  line-height: 1.65;
  color: #3a342c;
  margin-bottom: 24rpx;
}
.p.muted {
  color: #9a9186;
  font-size: 24rpx;
  margin-bottom: 0;
}
.footer {
  padding-top: 28rpx;
}
.check-row {
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
  margin-bottom: 24rpx;
}
.check-label {
  flex: 1;
  font-size: 28rpx;
  line-height: 1.45;
  color: #2f2a24;
}
.confirm {
  background: #2f604f;
  color: #f7f4ef;
  border-radius: 999rpx;
  font-weight: 600;
  border: none;
}
.confirm[disabled] {
  opacity: 0.45;
}
.cancel {
  margin-top: 20rpx;
  background: transparent;
  color: #9a9186;
  border: none;
}
</style>
