import { request } from "../../../core/http";

export async function fetchProducts() {
  return request<{ items: any[] }>("/api/mall/products", { method: "GET" });
}

export async function fetchProductDetail(productId: string) {
  return request(`/api/mall/products/${productId}`, { method: "GET" });
}
