<template>
  <view class="page">
    <view class="hero">
      <view class="eyebrow">CHUXIN MALL</view>
      <view class="title">初心商城</view>
      <view class="subtitle">精选好物，安心购买</view>
    </view>

    <view v-if="loading" class="hint">加载中...</view>
    <view v-else-if="!products.length" class="hint">暂无商品，敬请期待</view>
    <view v-else class="list">
      <view
        v-for="item in products"
        :key="item.product_id"
        class="card"
        @tap="openDetail(item.product_id)"
      >
        <image v-if="item.cover_url" class="cover" :src="item.cover_url" mode="aspectFill" />
        <view v-else class="cover placeholder">暂无图</view>
        <view class="info">
          <view class="name">{{ item.name }}</view>
          <view class="desc">{{ item.description || "实体商品" }}</view>
          <view class="price">¥{{ item.min_price_yuan || "—" }}</view>
        </view>
      </view>
    </view>
    <view v-if="message" class="message">{{ message }}</view>
  </view>
</template>

<script setup lang="ts">
import { onShow } from "@dcloudio/uni-app";
import { ref } from "vue";
import { fetchProducts } from "../api/product";

const loading = ref(false);
const message = ref("");
const products = ref<any[]>([]);

onShow(() => {
  loadProducts();
});

async function loadProducts() {
  loading.value = true;
  message.value = "";
  try {
    const data = await fetchProducts();
    products.value = Array.isArray(data.items) ? data.items : [];
  } catch (error: any) {
    message.value = error.message || String(error);
  } finally {
    loading.value = false;
  }
}

function openDetail(productId: string) {
  uni.navigateTo({ url: `/modules/mall/pages/goods/detail?product_id=${productId}` });
}
</script>

<style scoped>
.page {
  min-height: 100vh;
  padding: 40rpx 32rpx 64rpx;
  background: linear-gradient(180deg, #f8f1e7 0%, #ece7df 100%);
}
.hero { margin-bottom: 28rpx; }
.eyebrow { color: #9b6146; font-size: 22rpx; letter-spacing: 2rpx; }
.title { color: #24211c; font-size: 48rpx; font-weight: 700; margin-top: 10rpx; }
.subtitle { color: #6f665b; font-size: 26rpx; margin-top: 10rpx; }
.hint { color: #82786d; font-size: 28rpx; padding: 40rpx 0; text-align: center; }
.list { display: flex; flex-direction: column; gap: 20rpx; }
.card {
  display: flex;
  gap: 20rpx;
  padding: 20rpx;
  background: rgba(255, 252, 246, 0.95);
  border-radius: 20rpx;
  border: 1rpx solid rgba(128, 94, 69, 0.14);
}
.cover { width: 160rpx; height: 160rpx; border-radius: 16rpx; flex-shrink: 0; }
.cover.placeholder {
  display: flex; align-items: center; justify-content: center;
  background: #ece7df; color: #82786d; font-size: 22rpx;
}
.info { flex: 1; min-width: 0; }
.name { color: #24211c; font-size: 30rpx; font-weight: 700; }
.desc { color: #82786d; font-size: 24rpx; margin-top: 8rpx; }
.price { color: #2f604f; font-size: 32rpx; font-weight: 700; margin-top: 16rpx; }
.message { color: #9e3b35; font-size: 26rpx; margin-top: 20rpx; }
</style>
