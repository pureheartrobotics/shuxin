<template>
  <view class="page">
    <view v-if="loading" class="hint">加载中...</view>
    <view v-else>
      <view v-for="addr in items" :key="addr.address_id" class="card">
        <view class="head">
          <text>{{ addr.receiver_name }} {{ addr.receiver_phone }}</text>
          <text v-if="addr.is_default" class="badge">默认</text>
        </view>
        <view class="line">
          {{ addr.province }}{{ addr.city }}{{ addr.district }}{{ addr.detail }}
        </view>
        <view class="actions">
          <button class="mini" @tap="edit(addr)">编辑</button>
          <button class="mini" v-if="!addr.is_default" @tap="makeDefault(addr.address_id)">设默认</button>
          <button class="mini danger" @tap="remove(addr.address_id)">删除</button>
        </view>
      </view>
      <view v-if="!items.length" class="hint">暂无地址，请新增</view>
    </view>

    <view class="form">
      <view class="form-title">{{ editingId ? "编辑地址" : "新增地址" }}</view>
      <input v-model="form.receiver_name" placeholder="收货人" />
      <input v-model="form.receiver_phone" placeholder="手机号" />
      <input v-model="form.province" placeholder="省" />
      <input v-model="form.city" placeholder="市" />
      <input v-model="form.district" placeholder="区" />
      <input v-model="form.detail" placeholder="详细地址" />
      <label class="check">
        <checkbox :checked="form.is_default" @tap="form.is_default = !form.is_default" />
        设为默认
      </label>
      <button class="primary" @tap="save">{{ editingId ? "保存修改" : "保存地址" }}</button>
      <button v-if="editingId" class="secondary" @tap="resetForm">取消编辑</button>
    </view>
    <view v-if="message" class="message">{{ message }}</view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { reactive, ref } from "vue";
import {
  createAddress,
  deleteAddress,
  fetchAddresses,
  setDefaultAddress,
  updateAddress,
} from "../../api/address";

const loading = ref(false);
const message = ref("");
const items = ref<any[]>([]);
const editingId = ref("");
const form = reactive({
  receiver_name: "",
  receiver_phone: "",
  province: "",
  city: "",
  district: "",
  detail: "",
  is_default: true,
});

onShow(() => load());

async function load() {
  loading.value = true;
  message.value = "";
  try {
    const data = await fetchAddresses();
    items.value = data.items || [];
  } catch (error: any) {
    message.value = error.message || String(error);
  } finally {
    loading.value = false;
  }
}

function resetForm() {
  editingId.value = "";
  form.receiver_name = "";
  form.receiver_phone = "";
  form.province = "";
  form.city = "";
  form.district = "";
  form.detail = "";
  form.is_default = true;
}

function edit(addr: any) {
  editingId.value = addr.address_id;
  form.receiver_name = addr.receiver_name;
  form.receiver_phone = addr.receiver_phone;
  form.province = addr.province;
  form.city = addr.city;
  form.district = addr.district;
  form.detail = addr.detail;
  form.is_default = !!addr.is_default;
}

async function save() {
  try {
    if (editingId.value) {
      await updateAddress(editingId.value, { ...form });
    } else {
      await createAddress({ ...form });
    }
    resetForm();
    await load();
    uni.showToast({ title: "已保存", icon: "success" });
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}

async function remove(addressId: string) {
  try {
    await deleteAddress(addressId);
    await load();
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}

async function makeDefault(addressId: string) {
  try {
    await setDefaultAddress(addressId);
    await load();
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}
</script>

<style scoped>
.page { padding: 32rpx; background: #f5f1ea; min-height: 100vh; }
.hint { text-align: center; color: #82786d; padding: 40rpx 0; }
.card {
  background: #fffaf3; border-radius: 16rpx; padding: 20rpx; margin-bottom: 16rpx;
  border: 1rpx solid rgba(128,94,69,.12);
}
.head { display: flex; justify-content: space-between; font-weight: 700; color: #24211c; }
.badge { color: #2f604f; font-size: 22rpx; }
.line { margin-top: 8rpx; color: #82786d; font-size: 26rpx; }
.actions { display: flex; gap: 12rpx; margin-top: 16rpx; }
.mini { font-size: 22rpx; background: #ece7df; color: #4a5d52; }
.mini.danger { background: #f3ded9; color: #9e3b35; }
.form { margin-top: 28rpx; }
.form-title { font-size: 30rpx; font-weight: 700; margin-bottom: 12rpx; color: #24211c; }
input { background: #fffaf3; margin-bottom: 16rpx; padding: 20rpx; border-radius: 12rpx; }
.check { display: flex; align-items: center; gap: 8rpx; color: #4a5d52; margin-bottom: 12rpx; }
.primary { background: #2f604f; color: #fffaf3; margin-top: 12rpx; }
.secondary { background: #ece7df; color: #4a5d52; margin-top: 12rpx; }
.message { color: #9e3b35; margin-top: 16rpx; }
</style>
