<template>
  <view class="page">
    <view v-if="loading" class="hint">加载中...</view>
    <view v-else-if="product" class="panel">
      <image v-if="product.cover_url" class="cover" :src="product.cover_url" mode="aspectFill" />
      <view class="name">{{ product.name }}</view>
      <view class="desc">{{ product.description }}</view>
      <view class="sku-list">
        <view
          v-for="sku in product.skus"
          :key="sku.sku_id"
          class="sku"
          :class="{ active: selectedSkuId === sku.sku_id }"
          @tap="selectedSkuId = sku.sku_id"
        >
          <text>{{ sku.name }} · ¥{{ sku.price_yuan }}</text>
          <text class="stock">库存 {{ sku.stock }}</text>
        </view>
      </view>
      <button class="primary" :disabled="!selectedSkuId || adding" @tap="addToCart">加入购物车</button>
      <button class="secondary" @tap="goCart">查看购物车</button>
    </view>
    <view v-if="message" class="message">{{ message }}</view>
  </view>
</template>

<script setup lang="ts">
import { onLoad } from "@dcloudio/uni-app";
import { ref } from "vue";
import { fetchProductDetail } from "../../api/product";
import { upsertCartItem } from "../../api/cart";

const loading = ref(true);
const adding = ref(false);
const message = ref("");
const product = ref<any>(null);
const selectedSkuId = ref("");
let productId = "";

onLoad((query) => {
  productId = String(query?.product_id || "");
  loadDetail();
});

async function loadDetail() {
  loading.value = true;
  message.value = "";
  try {
    product.value = await fetchProductDetail(productId);
    const skus = product.value?.skus || [];
    if (skus.length) selectedSkuId.value = skus[0].sku_id;
  } catch (error: any) {
    message.value = error.message || String(error);
  } finally {
    loading.value = false;
  }
}

async function addToCart() {
  if (!selectedSkuId.value) return;
  adding.value = true;
  try {
    await upsertCartItem(selectedSkuId.value, 1);
    uni.showToast({ title: "已加入购物车", icon: "success" });
  } catch (error: any) {
    message.value = error.message || String(error);
  } finally {
    adding.value = false;
  }
}

function goCart() {
  uni.navigateTo({ url: "/modules/mall/pages/cart/index" });
}
</script>

<style scoped>
.page { min-height: 100vh; padding: 32rpx; background: #f5f1ea; }
.hint { text-align: center; color: #82786d; padding: 60rpx 0; }
.panel { background: #fffaf3; border-radius: 24rpx; padding: 28rpx; }
.cover { width: 100%; height: 360rpx; border-radius: 20rpx; }
.name { font-size: 40rpx; font-weight: 700; color: #24211c; margin-top: 24rpx; }
.desc { font-size: 26rpx; color: #82786d; margin-top: 12rpx; line-height: 1.6; }
.sku-list { margin-top: 24rpx; display: flex; flex-direction: column; gap: 12rpx; }
.sku {
  padding: 20rpx; border-radius: 16rpx; border: 1rpx solid rgba(128,94,69,.14);
  display: flex; justify-content: space-between; color: #24211c;
}
.sku.active { border-color: #2f604f; background: #e4eee8; }
.stock { color: #82786d; font-size: 24rpx; }
.primary, .secondary { margin-top: 20rpx; }
.primary { background: #2f604f; color: #fffaf3; }
.secondary { background: #ece7df; color: #4a5d52; }
.message { color: #9e3b35; margin-top: 20rpx; }
</style>
