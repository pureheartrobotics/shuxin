<template>
  <view class="page">
    <view v-if="loading" class="hint">加载中...</view>
    <view v-else-if="!items.length" class="hint">购物车是空的</view>
    <view v-else>
      <view v-for="item in items" :key="item.cart_item_id" class="row">
        <view class="info">
          <view class="name">{{ item.product_name }}</view>
          <view class="sku">{{ item.sku_name }} · ¥{{ item.price_yuan }}</view>
          <view class="qty">
            <button class="qty-btn" @tap="setQty(item, item.quantity - 1)">-</button>
            <text class="qty-num">{{ item.quantity }}</text>
            <button class="qty-btn" @tap="setQty(item, item.quantity + 1)">+</button>
          </view>
        </view>
        <button class="mini" @tap="remove(item.cart_item_id)">删除</button>
      </view>
      <view class="total">合计 ¥{{ totalYuan }}</view>
      <button class="primary" @tap="goConfirm">去结算</button>
    </view>
    <view v-if="message" class="message">{{ message }}</view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { ref } from "vue";
import { fetchCart, removeCartItem, upsertCartItem } from "../../api/cart";

const loading = ref(false);
const message = ref("");
const items = ref<any[]>([]);
const totalYuan = ref(0);

onShow(() => loadCart());

async function loadCart() {
  loading.value = true;
  message.value = "";
  try {
    const data = await fetchCart();
    items.value = data.items || [];
    totalYuan.value = data.total_yuan || 0;
  } catch (error: any) {
    message.value = error.message || String(error);
  } finally {
    loading.value = false;
  }
}

async function setQty(item: any, qty: number) {
  if (qty <= 0) {
    await remove(item.cart_item_id);
    return;
  }
  try {
    const data = await upsertCartItem(item.sku_id, qty);
    items.value = data.items || [];
    totalYuan.value = data.total_yuan || 0;
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}

async function remove(cartItemId: string) {
  try {
    const data = await removeCartItem(cartItemId);
    items.value = data.items || [];
    totalYuan.value = data.total_yuan || 0;
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}

function goConfirm() {
  uni.navigateTo({ url: "/modules/mall/pages/order/confirm" });
}
</script>

<style scoped>
.page { min-height: 100vh; padding: 32rpx; background: #f5f1ea; }
.hint { text-align: center; color: #82786d; padding: 80rpx 0; }
.row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 24rpx 0; border-bottom: 1rpx solid rgba(128,94,69,.12);
}
.name { font-size: 30rpx; font-weight: 700; color: #24211c; }
.sku { font-size: 24rpx; color: #82786d; margin-top: 8rpx; }
.qty { display: flex; align-items: center; gap: 12rpx; margin-top: 12rpx; }
.qty-btn {
  width: 48rpx; height: 48rpx; line-height: 48rpx; padding: 0;
  background: #ece7df; color: #2f604f; font-size: 28rpx;
}
.qty-num { min-width: 36rpx; text-align: center; }
.mini { font-size: 24rpx; background: #f3ded9; color: #9e3b35; }
.total { text-align: right; font-size: 34rpx; font-weight: 700; color: #2f604f; margin: 28rpx 0; }
.primary { background: #2f604f; color: #fffaf3; }
.message { color: #9e3b35; margin-top: 16rpx; }
</style>
