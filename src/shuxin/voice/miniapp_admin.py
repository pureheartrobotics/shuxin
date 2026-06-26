from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Any, Optional
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("shuxin.voice.miniapp_admin")

miniapp_admin_router = APIRouter()

def _get_miniapp_admin_token() -> str:
    """获取小程序管理后台 Token。"""
    token = os.environ.get("SHUXIN_MINIAPP_ADMIN_TOKEN")
    if not token:
        token = os.environ.get("SHUXIN_ADMIN_TOKEN")
    return token or "dev-miniapp-admin-token"

def require_miniapp_admin(request: Request) -> None:
    """验证小程序管理后台登录状态。"""
    token = _get_miniapp_admin_token()
    provided = request.headers.get("X-Miniapp-Admin-Token") or request.cookies.get("shuxin_miniapp_admin")
    if not provided or provided != token:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid admin token")

class LoginPayload(BaseModel):
    token: str

class AnnouncementPayload(BaseModel):
    id: Optional[int] = None
    title: str
    content: str
    type: str
    is_active: bool = True
    start_time: Optional[str] = None
    end_time: Optional[str] = None

class FeedbackUpdatePayload(BaseModel):
    status: str
    admin_notes: str

@miniapp_admin_router.post("/api/login")
async def admin_login(payload: LoginPayload, response: Response):
    token = _get_miniapp_admin_token()
    if payload.token != token:
        return JSONResponse({"error": "invalid admin token"}, status_code=403)
    
    response.set_cookie(
        key="shuxin_miniapp_admin",
        value=token,
        max_age=86400 * 30,  # 30 days
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}

@miniapp_admin_router.post("/api/logout")
async def admin_logout(response: Response):
    response.delete_cookie("shuxin_miniapp_admin")
    return {"ok": True}

@miniapp_admin_router.get("/api/announcements")
async def list_announcements(request: Request, limit: int = 50, offset: int = 0):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    items = await repo.admin_list_announcements(limit=limit, offset=offset)
    return {"items": items}

@miniapp_admin_router.post("/api/announcements")
async def upsert_announcement(request: Request, payload: AnnouncementPayload):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    
    start_dt = None
    if payload.start_time:
        try:
            start_dt = datetime.fromisoformat(payload.start_time.replace("Z", "+00:00"))
        except ValueError:
            pass
            
    end_dt = None
    if payload.end_time:
        try:
            end_dt = datetime.fromisoformat(payload.end_time.replace("Z", "+00:00"))
        except ValueError:
            pass

    result = await repo.admin_upsert_announcement(
        announcement_id=payload.id,
        title=payload.title,
        content=payload.content,
        type=payload.type,
        is_active=payload.is_active,
        start_time=start_dt,
        end_time=end_dt
    )
    return result

@miniapp_admin_router.delete("/api/announcements/{announcement_id}")
async def delete_announcement(request: Request, announcement_id: int):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_delete_announcement(announcement_id)
    return result

@miniapp_admin_router.get("/api/feedbacks")
async def list_feedbacks(request: Request, limit: int = 50, offset: int = 0, status: Optional[str] = None):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    items = await repo.admin_list_feedbacks(limit=limit, offset=offset, status=status)
    return {"items": items}

@miniapp_admin_router.put("/api/feedbacks/{feedback_id}")
async def update_feedback(request: Request, feedback_id: int, payload: FeedbackUpdatePayload):
    require_miniapp_admin(request)
    repo = request.app.state.repo
    result = await repo.admin_update_feedback(
        feedback_id,
        status=payload.status,
        admin_notes=payload.admin_notes
    )
    return result

@miniapp_admin_router.get("", response_class=HTMLResponse)
async def admin_portal(request: Request):
    """渲染精美的小程序专属后台管理界面。"""
    token = _get_miniapp_admin_token()
    provided = request.headers.get("X-Miniapp-Admin-Token") or request.cookies.get("shuxin_miniapp_admin")
    authenticated = (provided == token)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>初心小程序运营管理后台</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Outfit', 'Noto Sans SC', sans-serif;
            background-color: #0b0f19;
            color: #f3f4f6;
        }}
        .glass {{
            background: rgba(17, 24, 39, 0.7);
            backdrop-filter: blur(12px);
            border: 1px rgba(255, 255, 255, 0.08) solid;
        }}
    </style>
</head>
<body class="min-h-screen flex flex-col">
    <div id="app" class="flex-grow flex flex-col" v-cloak>
        <!-- 登录框 -->
        <div v-if="!authenticated" class="flex-grow flex items-center justify-center px-4">
            <div class="glass w-full max-w-md p-8 rounded-2xl shadow-2xl space-y-6">
                <div class="text-center">
                    <div class="inline-flex p-3 rounded-full bg-indigo-500/10 text-indigo-400 mb-3">
                        <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 3m0-3a2 2 0 110 3m-9 11h18M2 17V7a2 2 0 012-2h16a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2z" />
                        </svg>
                    </div>
                    <h2 class="text-2xl font-bold tracking-tight">初心运营管理后台</h2>
                    <p class="text-gray-400 text-sm mt-1">管理小程序公告与查看用户反馈</p>
                </div>
                <form @submit.prevent="handleLogin" class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">管理凭证 (Token)</label>
                        <input type="password" v-model="loginToken" required 
                            placeholder="请输入运营管理 Token"
                            class="w-full px-4 py-3 rounded-xl bg-gray-900/80 border border-gray-800 text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition duration-200">
                    </div>
                    <button type="submit" :disabled="loading"
                        class="w-full py-3 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition duration-200 disabled:opacity-50">
                        {{{{ loading ? '登录中...' : '进入控制台' }}}}
                    </button>
                    <p v-if="errorMsg" class="text-rose-500 text-sm text-center">{{{{ errorMsg }}}}</p>
                </form>
            </div>
        </div>

        <!-- 控制台主界面 -->
        <div v-else class="flex flex-col md:flex-row min-h-screen">
            <!-- 侧边栏 -->
            <aside class="w-full md:w-64 glass border-r border-gray-800 flex flex-col">
                <div class="p-6 border-b border-gray-800 flex items-center space-x-3">
                    <span class="text-2xl">🦊</span>
                    <div>
                        <h1 class="font-bold text-lg leading-tight">初心·小助手</h1>
                        <span class="text-xs text-indigo-400 font-medium tracking-wider uppercase">MINIAPP ADMIN</span>
                    </div>
                </div>
                <nav class="flex-grow p-4 space-y-1">
                    <button @click="currentTab = 'announcements'" 
                        :class="currentTab === 'announcements' ? 'bg-indigo-600/10 text-indigo-400 border-l-4 border-indigo-500' : 'text-gray-400 hover:bg-gray-850 hover:text-gray-200'"
                        class="w-full flex items-center px-4 py-3 rounded-xl font-medium text-left transition duration-150">
                        <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6M5.436 13.683A4.001 4.001 0 017 6h1.832c4.1 0 7.625-1.234 9.168-3v14c-1.543-1.766-5.067-3-9.168-3H7a3.988 3.988 0 01-1.564-.317z" />
                        </svg>
                        公告公告发布
                    </button>
                    <button @click="currentTab = 'feedbacks'" 
                        :class="currentTab === 'feedbacks' ? 'bg-indigo-600/10 text-indigo-400 border-l-4 border-indigo-500' : 'text-gray-400 hover:bg-gray-850 hover:text-gray-200'"
                        class="w-full flex items-center px-4 py-3 rounded-xl font-medium text-left transition duration-150">
                        <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                        用户意见反馈
                    </button>
                </nav>
                <div class="p-4 border-t border-gray-800">
                    <button @click="handleLogout" 
                        class="w-full py-2.5 px-4 rounded-xl border border-gray-850 text-gray-400 hover:text-white hover:bg-gray-900 transition duration-150 text-sm font-medium">
                        退出系统
                    </button>
                </div>
            </aside>

            <!-- 主要内容区 -->
            <main class="flex-grow p-6 md:p-10 overflow-y-auto max-w-6xl mx-auto w-full">
                <!-- 顶栏 -->
                <header class="mb-8 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                    <div>
                        <h2 class="text-3xl font-bold tracking-tight">
                            {{{{ currentTab === 'announcements' ? '公告管理' : '用户意见反馈' }}}}
                        </h2>
                        <p class="text-gray-400 text-sm mt-1">
                            {{{{ currentTab === 'announcements' ? '发布小程序端顶部通知横幅或紧急大屏弹窗' : '查看小程序用户的意见反馈和客服跟进' }}}}
                        </p>
                    </div>
                    <div v-if="currentTab === 'announcements'">
                        <button @click="openAddAnnouncementModal"
                            class="bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 px-5 rounded-xl transition shadow-lg shadow-indigo-600/20 flex items-center">
                            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                            </svg>
                            发布新公告
                        </button>
                    </div>
                </header>

                <!-- 公告列表选项卡 -->
                <div v-if="currentTab === 'announcements'" class="space-y-6">
                    <div class="glass rounded-2xl overflow-hidden shadow-xl border border-gray-800">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-gray-900/50 border-b border-gray-800 text-gray-400 text-xs uppercase tracking-wider font-semibold">
                                    <th class="py-4 px-6">公告类型</th>
                                    <th class="py-4 px-6">标题</th>
                                    <th class="py-4 px-6">公告内容</th>
                                    <th class="py-4 px-6">状态</th>
                                    <th class="py-4 px-6">发布时间</th>
                                    <th class="py-4 px-6 text-right">操作</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-800">
                                <tr v-if="!announcements.length" class="text-gray-500 text-center">
                                    <td colspan="6" class="py-12">暂无公告数据，点击右上方按钮发布第一条吧！</td>
                                </tr>
                                <tr v-for="item in announcements" :key="item.id" class="hover:bg-gray-900/25 transition duration-150">
                                    <td class="py-4 px-6">
                                        <span :class="item.type === 'popup' ? 'bg-rose-500/10 text-rose-400' : 'bg-amber-500/10 text-amber-400'"
                                            class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border border-current">
                                            {{{{ item.type === 'popup' ? '紧急弹窗' : '顶部横幅' }}}}
                                        </span>
                                    </td>
                                    <td class="py-4 px-6 font-semibold text-white">{{{{ item.title }}}}</td>
                                    <td class="py-4 px-6 text-gray-300 max-w-xs truncate" :title="item.content">{{{{ item.content }}}}</td>
                                    <td class="py-4 px-6">
                                        <span :class="item.is_active ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-gray-800 text-gray-500 border-gray-700'"
                                            class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border">
                                            {{{{ item.is_active ? '生效中' : '已停用' }}}}
                                        </span>
                                    </td>
                                    <td class="py-4 px-6 text-sm text-gray-400">{{{{ formatTime(item.created_at) }}}}</td>
                                    <td class="py-4 px-6 text-right space-x-2">
                                        <button @click="editAnnouncement(item)" class="text-indigo-400 hover:text-indigo-300 font-medium text-sm transition">编辑</button>
                                        <button @click="deleteAnnouncement(item.id)" class="text-rose-400 hover:text-rose-300 font-medium text-sm transition">删除</button>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- 意见反馈选项卡 -->
                <div v-if="currentTab === 'feedbacks'" class="space-y-6">
                    <!-- 反馈过滤器 -->
                    <div class="flex space-x-2 border-b border-gray-800 pb-4">
                        <button v-for="s in ['all', 'pending', 'processed', 'ignored']" 
                            :key="s"
                            @click="feedbackFilter = s"
                            :class="feedbackFilter === s ? 'bg-gray-800 text-white font-medium border border-gray-700' : 'text-gray-400 hover:text-white'"
                            class="px-4 py-2 rounded-xl text-sm transition">
                            {{{{ s === 'all' ? '全部' : s === 'pending' ? '待处理' : s === 'processed' ? '已处理' : '已忽略' }}}}
                        </button>
                    </div>

                    <div class="grid gap-6 md:grid-cols-2">
                        <div v-if="!filteredFeedbacks.length" class="col-span-full text-center py-16 glass rounded-2xl text-gray-500">
                            没有找到对应的用户反馈记录。
                        </div>
                        <div v-for="fb in filteredFeedbacks" :key="fb.id" class="glass p-6 rounded-2xl flex flex-col justify-between shadow-lg relative border border-gray-800 hover:border-gray-700 transition">
                            <span :class="fb.status === 'pending' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : fb.status === 'processed' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-gray-800 text-gray-500 border-gray-700'"
                                class="absolute top-6 right-6 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border">
                                {{{{ fb.status === 'pending' ? '待处理' : fb.status === 'processed' ? '已处理' : '已忽略' }}}}
                            </span>
                            <div class="space-y-4">
                                <div class="flex items-center space-x-3">
                                    <div class="w-10 h-10 rounded-full bg-gray-800 flex items-center justify-center font-bold text-indigo-400">
                                        {{{{ fb.user_id.slice(-4) }}}}
                                    </div>
                                    <div>
                                        <div class="text-sm font-semibold text-white">用户 ID: {{{{ fb.user_id }}}}</div>
                                        <div class="text-xs text-gray-500">提交于: {{{{ formatTime(fb.created_at) }}}}</div>
                                    </div>
                                </div>
                                <div class="bg-gray-950/40 p-4 rounded-xl border border-gray-900/80 text-gray-200 text-sm whitespace-pre-wrap leading-relaxed">
                                    {{{{ fb.content }}}}
                                </div>
                                <div class="text-sm text-gray-400">
                                    <strong class="text-gray-300 text-xs uppercase tracking-wider block mb-1">联系方式</strong>
                                    {{{{ fb.contact || '用户未提供联系方式' }}}}
                                </div>
                                <div v-if="fb.admin_notes" class="bg-indigo-950/20 p-3 rounded-xl border border-indigo-900/30 text-indigo-300 text-xs">
                                    <strong class="text-indigo-400 block mb-1">跟进记录：</strong>
                                    {{{{ fb.admin_notes }}}}
                                </div>
                            </div>
                            <div class="mt-6 pt-4 border-t border-gray-850 flex justify-end space-x-3">
                                <button @click="openFeedbackModal(fb)" 
                                    class="text-indigo-400 hover:bg-indigo-500/10 hover:text-indigo-300 border border-indigo-500/20 rounded-xl px-4 py-2 text-sm font-medium transition">
                                    处理 / 备注
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>

        <!-- 新增/编辑公告 Modal -->
        <div v-if="showAnnouncementModal" class="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div class="glass w-full max-w-xl p-8 rounded-2xl shadow-2xl space-y-6 max-h-[90vh] overflow-y-auto">
                <div class="flex justify-between items-center pb-4 border-b border-gray-850">
                    <h3 class="text-xl font-bold text-white">{{{{ form.id ? '编辑公告' : '发布新公告' }}}}</h3>
                    <button @click="showAnnouncementModal = false" class="text-gray-400 hover:text-white">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>
                <form @submit.prevent="submitAnnouncement" class="space-y-4">
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-300 mb-1">公告类型</label>
                            <select v-model="form.type" required
                                class="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50">
                                <option value="banner">顶部横幅通知</option>
                                <option value="popup">紧急弹窗大屏</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-300 mb-1">启用状态</label>
                            <div class="flex items-center h-[42px]">
                                <input type="checkbox" v-model="form.is_active" id="is_active" 
                                    class="w-5 h-5 text-indigo-600 bg-gray-900 border-gray-800 rounded focus:ring-indigo-500/50">
                                <label for="is_active" class="ml-2 text-sm text-gray-300 cursor-pointer">生效中</label>
                            </div>
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">公告标题</label>
                        <input type="text" v-model="form.title" required placeholder="请输入公告标题，例如：系统升级公告"
                            class="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50">
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">公告正文内容</label>
                        <textarea v-model="form.content" required rows="4" placeholder="请输入公告正文详细内容..."
                            class="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50"></textarea>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-300 mb-1">开始时间 (可选)</label>
                            <input type="datetime-local" v-model="form.start_time"
                                class="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-300 mb-1">结束时间 (可选)</label>
                            <input type="datetime-local" v-model="form.end_time"
                                class="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50">
                        </div>
                    </div>
                    <div class="flex justify-end space-x-3 pt-4 border-t border-gray-850">
                        <button type="button" @click="showAnnouncementModal = false"
                            class="px-5 py-2.5 rounded-xl border border-gray-800 text-gray-400 hover:text-white transition">取消</button>
                        <button type="submit" :disabled="loading"
                            class="bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 px-6 rounded-xl transition">
                            保存发布
                        </button>
                    </div>
                </form>
            </div>
        </div>

        <!-- 意见反馈处理 Modal -->
        <div v-if="showFeedbackModal" class="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 z-50">
            <div class="glass w-full max-w-lg p-8 rounded-2xl shadow-2xl space-y-6">
                <div class="flex justify-between items-center pb-4 border-b border-gray-850">
                    <h3 class="text-xl font-bold text-white">跟进处理反馈</h3>
                    <button @click="showFeedbackModal = false" class="text-gray-400 hover:text-white">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>
                <form @submit.prevent="submitFeedbackUpdate" class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">用户反馈原内容</label>
                        <div class="bg-gray-950 p-4 rounded-xl border border-gray-900 text-gray-400 text-sm max-h-32 overflow-y-auto">
                            {{{{ selectedFeedback.content }}}}
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">处理状态</label>
                        <select v-model="feedbackForm.status" required
                            class="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50">
                            <option value="pending">待处理</option>
                            <option value="processed">已处理（完成）</option>
                            <option value="ignored">忽略（不予处理）</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">内部备注 / 跟进记录</label>
                        <textarea v-model="feedbackForm.admin_notes" rows="4" placeholder="请在此记录电话回访或系统问题修复进度..."
                            class="w-full px-4 py-2.5 rounded-xl bg-gray-900 border border-gray-800 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50"></textarea>
                    </div>
                    <div class="flex justify-end space-x-3 pt-4 border-t border-gray-850">
                        <button type="button" @click="showFeedbackModal = false"
                            class="px-5 py-2.5 rounded-xl border border-gray-800 text-gray-400 hover:text-white transition">取消</button>
                        <button type="submit" :disabled="loading"
                            class="bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 px-6 rounded-xl transition">
                            确认保存
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <script>
        const {{ createApp, ref, computed, onMounted }} = Vue;

        createApp({{
            setup() {{
                const authenticated = ref({str(authenticated).lower()});
                const loginToken = ref('');
                const loading = ref(false);
                const errorMsg = ref('');
                
                const currentTab = ref('announcements');
                const announcements = ref([]);
                const feedbacks = ref([]);
                const feedbackFilter = ref('all');

                // 公告表单
                const showAnnouncementModal = ref(false);
                const form = ref({{
                    id: null,
                    title: '',
                    content: '',
                    type: 'banner',
                    is_active: true,
                    start_time: '',
                    end_time: ''
                }});

                // 反馈表单
                const showFeedbackModal = ref(false);
                const selectedFeedback = ref({{}});
                const feedbackForm = ref({{
                    status: 'pending',
                    admin_notes: ''
                }});

                const filteredFeedbacks = computed(() => {{
                    if (feedbackFilter.value === 'all') return feedbacks.value;
                    return feedbacks.value.filter(fb => fb.status === feedbackFilter.value);
                }});

                const apiRequest = async (path, method = 'GET', body = null) => {{
                    const headers = {{ 'Content-Type': 'application/json' }};
                    const options = {{ method, headers }};
                    if (body) {{
                        options.body = JSON.stringify(body);
                    }}
                    const res = await fetch(`/miniapp-admin${{path}}`, options);
                    if (res.status === 401) {{
                        authenticated.value = false;
                        throw new Error('未授权，请登录');
                    }}
                    const data = await res.json();
                    if (data.error) throw new Error(data.error);
                    return data;
                }};

                const handleLogin = async () => {{
                    loading.value = true;
                    errorMsg.value = '';
                    try {{
                        await apiRequest('/api/login', 'POST', {{ token: loginToken.value }});
                        authenticated.value = true;
                        loginToken.value = '';
                        loadData();
                    }} catch (err) {{
                        errorMsg.value = err.message;
                    }} finally {{
                        loading.value = false;
                    }}
                }};

                const handleLogout = async () => {{
                    try {{
                        await apiRequest('/api/logout', 'POST');
                    }} finally {{
                        authenticated.value = false;
                    }}
                }};

                const loadData = async () => {{
                    if (!authenticated.value) return;
                    try {{
                        const [annRes, fbRes] = await Promise.all([
                            apiRequest('/api/announcements'),
                            apiRequest('/api/feedbacks')
                        ]);
                        announcements.value = annRes.items || [];
                        feedbacks.value = fbRes.items || [];
                    }} catch (err) {{
                        console.error('加载数据失败:', err);
                    }}
                }};

                const openAddAnnouncementModal = () => {{
                    form.value = {{
                        id: null,
                        title: '',
                        content: '',
                        type: 'banner',
                        is_active: true,
                        start_time: '',
                        end_time: ''
                    }};
                    showAnnouncementModal.value = true;
                }};

                const editAnnouncement = (item) => {{
                    // datetime-local input requires YYYY-MM-DDTHH:MM
                    let startStr = '';
                    if (item.start_time) {{
                        startStr = item.start_time.slice(0, 16);
                    }}
                    let endStr = '';
                    if (item.end_time) {{
                        endStr = item.end_time.slice(0, 16);
                    }}
                    form.value = {{
                        id: item.id,
                        title: item.title,
                        content: item.content,
                        type: item.type,
                        is_active: item.is_active,
                        start_time: startStr,
                        end_time: endStr
                    }};
                    showAnnouncementModal.value = true;
                }};

                const submitAnnouncement = async () => {{
                    loading.value = true;
                    try {{
                        const payload = {{ ...form.value }};
                        // format to ISO format
                        if (payload.start_time) payload.start_time = new Date(payload.start_time).toISOString();
                        if (payload.end_time) payload.end_time = new Date(payload.end_time).toISOString();
                        
                        await apiRequest('/api/announcements', 'POST', payload);
                        showAnnouncementModal.value = false;
                        loadData();
                    }} catch (err) {{
                        alert(err.message);
                    }} finally {{
                        loading.value = false;
                    }}
                }};

                const deleteAnnouncement = async (id) => {{
                    if (!confirm('确定要删除这条公告吗？用户将无法再看到它。')) return;
                    try {{
                        await apiRequest(`/api/announcements/${{id}}`, 'DELETE');
                        loadData();
                    }} catch (err) {{
                        alert(err.message);
                    }}
                }};

                const openFeedbackModal = (fb) => {{
                    selectedFeedback.value = fb;
                    feedbackForm.value = {{
                        status: fb.status,
                        admin_notes: fb.admin_notes || ''
                    }};
                    showFeedbackModal.value = true;
                }};

                const submitFeedbackUpdate = async () => {{
                    loading.value = true;
                    try {{
                        await apiRequest(`/api/feedbacks/${{selectedFeedback.value.id}}`, 'PUT', feedbackForm.value);
                        showFeedbackModal.value = false;
                        loadData();
                    }} catch (err) {{
                        alert(err.message);
                    }} finally {{
                        loading.value = false;
                    }}
                }};

                const formatTime = (timeStr) => {{
                    if (!timeStr) return '';
                    try {{
                        const date = new Date(timeStr);
                        return date.toLocaleString('zh-CN', {{ hour12: false }});
                    }} catch (e) {{
                        return timeStr;
                    }}
                }};

                onMounted(() => {{
                    loadData();
                }});

                return {{
                    authenticated,
                    loginToken,
                    loading,
                    errorMsg,
                    currentTab,
                    announcements,
                    feedbacks,
                    feedbackFilter,
                    filteredFeedbacks,
                    handleLogin,
                    handleLogout,
                    showAnnouncementModal,
                    form,
                    openAddAnnouncementModal,
                    editAnnouncement,
                    submitAnnouncement,
                    deleteAnnouncement,
                    showFeedbackModal,
                    selectedFeedback,
                    feedbackForm,
                    openFeedbackModal,
                    submitFeedbackUpdate,
                    formatTime
                }};
            }}
        }}).mount('#app');
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)
