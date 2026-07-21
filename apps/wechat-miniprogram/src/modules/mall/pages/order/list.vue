<template>
  <view class="page">
    <view v-if="loading" class="hint">加载中...</view>
    <view v-else-if="!orders.length" class="hint">暂无商城订单</view>
    <view v-else class="list">
      <view v-for="order in orders" :key="order.order_id" class="card">
        <view class="head">
          <text>{{ order.out_trade_no }}</text>
          <text class="status">{{ statusLabel(order.status) }}</text>
        </view>
        <view class="total">¥{{ order.total_yuan }}</view>
        <view v-for="item in order.items" :key="item.sku_id + '-' + item.quantity" class="line">
          {{ item.product_name }}{{ item.sku_name ? `（${item.sku_name}）` : "" }} × {{ item.quantity }}
        </view>
        <view v-if="order.shipping_carrier || order.shipping_no" class="ship">
          物流：{{ order.shipping_carrier || "快递" }}
          <text v-if="order.shipping_no"> {{ order.shipping_no }}</text>
        </view>
        <button
          v-if="order.status === 'pending'"
          class="cancel"
          @tap="cancel(order.order_id)"
        >
          取消订单
        </button>
      </view>
    </view>
    <view v-if="message" class="message">{{ message }}</view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { ref } from "vue";
import { cancelMallOrder, fetchOrders } from "../../api/order";

const loading = ref(false);
const message = ref("");
const orders = ref<any[]>([]);

onShow(() => loadOrders());

async function loadOrders() {
  loading.value = true;
  message.value = "";
  try {
    const data = await fetchOrders();
    orders.value = data.items || [];
  } catch (error: any) {
    message.value = error.message || String(error);
  } finally {
    loading.value = false;
  }
}

async function cancel(orderId: string) {
  try {
    await cancelMallOrder(orderId);
    await loadOrders();
    uni.showToast({ title: "已取消", icon: "success" });
  } catch (error: any) {
    message.value = error.message || String(error);
  }
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    pending: "待支付",
    paid: "已支付",
    shipped: "已发货",
    completed: "已完成",
    cancelled: "已取消",
  };
  return map[status] || status;
}
</script>

<style scoped>
.page { min-height: 100vh; padding: 32rpx; background: #f5f1ea; }
.hint { text-align: center; color: #82786d; padding: 80rpx 0; }
.card {
  background: #fffaf3; border-radius: 20rpx; padding: 24rpx; margin-bottom: 16rpx;
  border: 1rpx solid rgba(128,94,69,.12);
}
.head { display: flex; justify-content: space-between; font-size: 24rpx; color: #6f665b; }
.status { color: #2f604f; font-weight: 700; }
.total { font-size: 34rpx; font-weight: 700; color: #24211c; margin: 12rpx 0; }
.line { font-size: 26rpx; color: #82786d; margin-top: 6rpx; }
.ship { font-size: 24rpx; color: #4a5d52; margin-top: 12rpx; }
.cancel { margin-top: 16rpx; background: #f3ded9; color: #9e3b35; font-size: 26rpx; }
.message { color: #9e3b35; margin-top: 16rpx; }
</style>
