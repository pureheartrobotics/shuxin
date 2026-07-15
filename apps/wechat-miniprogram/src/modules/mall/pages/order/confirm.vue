<template>
  <view class="page">
    <view class="section">
      <view class="label">收货地址</view>
      <view v-if="!addresses.length" class="hint">暂无地址，请先添加</view>
      <view
        v-for="addr in addresses"
        :key="addr.address_id"
        class="addr"
        :class="{ active: selectedAddressId === addr.address_id }"
        @tap="selectedAddressId = addr.address_id"
      >
        <view>{{ addr.receiver_name }} {{ addr.receiver_phone }}</view>
        <view class="detail">{{ addr.province }}{{ addr.city }}{{ addr.district }}{{ addr.detail }}</view>
      </view>
      <button class="secondary" @tap="showForm = !showForm">{{ showForm ? "收起" : "新增地址" }}</button>
      <view v-if="showForm" class="form">
        <input v-model="form.receiver_name" placeholder="收货人" />
        <input v-model="form.receiver_phone" placeholder="手机号" />
        <input v-model="form.province" placeholder="省" />
        <input v-model="form.city" placeholder="市" />
        <input v-model="form.district" placeholder="区" />
        <input v-model="form.detail" placeholder="详细地址" />
        <button class="secondary" @tap="saveAddress">保存地址</button>
      </view>
    </view>
    <button class="primary" :disabled="!selectedAddressId || paying" @tap="submitOrder">微信支付下单</button>
    <view v-if="message" class="message">{{ message }}</view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { reactive, ref } from "vue";
import { createAddress, fetchAddresses } from "../../api/address";
import { createMallOrder } from "../../api/order";

const paying = ref(false);
const showForm = ref(false);
const message = ref("");
const addresses = ref<any[]>([]);
const selectedAddressId = ref("");
const form = reactive({
  receiver_name: "",
  receiver_phone: "",
  province: "",
  city: "",
  district: "",
  detail: "",
});

onShow(() => loadAddresses());

async function loadAddresses() {
  try {
    const data = await fetchAddresses();
    addresses.value = data.items || [];
    if (!selectedAddressId.value && addresses.value.length) {
      selectedAddressId.value = addresses.value[0].address_id;
    }
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}

async function saveAddress() {
  try {
    const data = await createAddress({ ...form, is_default: true });
    addresses.value = data.items || [];
    if (addresses.value.length) {
      selectedAddressId.value = addresses.value[0].address_id;
    }
    showForm.value = false;
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}

async function submitOrder() {
  if (!selectedAddressId.value) return;
  paying.value = true;
  message.value = "";
  try {
    await createMallOrder(selectedAddressId.value);
    uni.showToast({ title: "支付成功", icon: "success" });
    setTimeout(() => {
      uni.navigateTo({ url: "/modules/mall/pages/order/list" });
    }, 500);
  } catch (error: any) {
    const text = error.message || String(error);
    if (!text.includes("cancel")) message.value = text;
  } finally {
    paying.value = false;
  }
}
</script>

<style scoped>
.page { min-height: 100vh; padding: 32rpx; background: #f5f1ea; }
.section { background: #fffaf3; border-radius: 20rpx; padding: 24rpx; }
.label { font-size: 28rpx; font-weight: 700; color: #24211c; margin-bottom: 16rpx; }
.hint { color: #82786d; font-size: 26rpx; margin-bottom: 16rpx; }
.addr { padding: 20rpx; border-radius: 16rpx; border: 1rpx solid rgba(128,94,69,.14); margin-bottom: 12rpx; }
.addr.active { border-color: #2f604f; background: #e4eee8; }
.detail { color: #82786d; font-size: 24rpx; margin-top: 8rpx; }
.form input { background: #f5efe6; margin-bottom: 12rpx; padding: 16rpx; border-radius: 12rpx; }
.primary, .secondary { margin-top: 20rpx; }
.primary { background: #2f604f; color: #fffaf3; }
.secondary { background: #ece7df; color: #4a5d52; }
.message { color: #9e3b35; margin-top: 16rpx; }
</style>
