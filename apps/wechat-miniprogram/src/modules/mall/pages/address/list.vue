<template>
  <view class="page">
    <input v-model="form.receiver_name" placeholder="收货人" />
    <input v-model="form.receiver_phone" placeholder="手机号" />
    <input v-model="form.province" placeholder="省" />
    <input v-model="form.city" placeholder="市" />
    <input v-model="form.district" placeholder="区" />
    <input v-model="form.detail" placeholder="详细地址" />
    <button class="primary" @tap="save">保存</button>
    <view v-if="message" class="message">{{ message }}</view>
  </view>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { createAddress } from "../../api/address";

const message = ref("");
const form = reactive({
  receiver_name: "",
  receiver_phone: "",
  province: "",
  city: "",
  district: "",
  detail: "",
});

async function save() {
  try {
    await createAddress({ ...form, is_default: true });
    uni.navigateBack();
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}
</script>

<style scoped>
.page { padding: 32rpx; background: #f5f1ea; min-height: 100vh; }
input { background: #fffaf3; margin-bottom: 16rpx; padding: 20rpx; border-radius: 12rpx; }
.primary { background: #2f604f; color: #fffaf3; margin-top: 20rpx; }
.message { color: #9e3b35; margin-top: 16rpx; }
</style>
