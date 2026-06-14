import json
from pathlib import Path


APP_DIR = Path("apps/wechat-miniprogram")


def test_wechat_miniprogram_scaffold_uses_uni_app() -> None:
    package = json.loads((APP_DIR / "package.json").read_text(encoding="utf-8"))
    pages = json.loads((APP_DIR / "src/pages.json").read_text(encoding="utf-8"))

    assert package["scripts"]["dev:mp-weixin"] == "uni -p mp-weixin"
    assert "@dcloudio/uni-mp-weixin" in package["dependencies"]
    assert pages["pages"][0]["path"] == "pages/index/index"
    assert pages["pages"][1]["path"] == "pages/profile/profile"
    assert pages["pages"][2]["path"] == "pages/login/login"
    assert pages["tabBar"]["list"][0]["text"] == "绑定"
    assert pages["tabBar"]["list"][1]["text"] == "个人中心"
    assert (APP_DIR / "src/pages/login/login.vue").exists()
    assert (APP_DIR / "src/pages/index/index.vue").exists()
    assert (APP_DIR / "src/pages/profile/profile.vue").exists()


def test_wechat_miniprogram_has_login_page_for_real_flow() -> None:
    page = (APP_DIR / "src/pages/login/login.vue").read_text(encoding="utf-8")

    assert 'provider: "weixin"' in page
    assert "uni.login" in page
    assert '"/api/wechat/login"' in page
    assert "uni.setStorageSync" in page
    assert "shuxin_session_token" in page
    assert "隐私" in page
    assert "用户协议" in page
    assert "进入设备绑定" in page
    assert "uni.switchTab" in page
    assert 'url: "/pages/index/index"' in page


def test_wechat_miniprogram_uses_wx_login_and_device_apis() -> None:
    page = (APP_DIR / "src/pages/index/index.vue").read_text(encoding="utf-8")

    assert '"/api/devices/bind"' in page
    assert '"/api/devices/my"' in page
    assert "MbtiRevealModal" in page
    assert "unbindDevice" not in page
    assert "shuxin_session_token" in page
    assert "session_token" in page
    assert "VITE_SHUXIN_API_BASE" in page
    assert "device_code" in page
    assert "claim_code" in page
    assert 'ref<"device_code" | "claim_code">("claim_code")' in page
    assert "外壳认领码" in page
    assert "formatBindError" in page
    assert "不是设备密钥" in page
    assert "authStatus" in page
    assert "buildBindPayload" in page
    assert "looksLikeClaimCode" in page
    assert "微信身份已确认" in page
    assert "ensureLoggedIn" in page
    assert "uni.redirectTo" in page
    assert "uni.showToast" in page
    assert "绑定成功" in page
    assert "绑定失败" in page
    assert "resultKind" in page
    assert 'scanType: ["barCode"]' in page
    assert "onlyFromCamera: true" in page
    assert "相机扫码" in page
    assert "res.result || res.path" in page
    assert "传图识别" in page
    assert '"/api/barcodes/decode"' in page
    assert "chooseImage" in page
    assert "getFileSystemManager" in page
    assert '"/health"' in page
    assert "[kind]" in page
    assert "onShow" not in page


def test_wechat_miniprogram_profile_page_has_account_controls() -> None:
    page = (APP_DIR / "src/pages/profile/profile.vue").read_text(encoding="utf-8")

    assert "个人中心" in page
    assert "shuxin_session_token" in page
    assert '"/api/devices/my"' in page
    assert "session_token" in page
    assert "绑定设备" in page
    assert "退出登录" in page
    assert "uni.removeStorageSync" in page
    assert "uni.redirectTo" in page


def test_wechat_dev_script_does_not_write_secrets_to_source() -> None:
    script = Path("scripts/wechat_miniprogram_dev.sh").read_text(encoding="utf-8")

    assert "WECHAT_MINIPROGRAM_APPID" in script
    assert "VITE_SHUXIN_API_BASE" in script
    assert "DEFAULT_API_BASE=\"http://localhost:8765\"" in script
    assert "$API_BASE/health" in script
    assert "http://127.0.0.1:8765" in script
    assert "detect_wsl_api_base" not in script
    assert "\npnpm install" not in script
    assert "src/pages/index/index.vue" not in script
    assert "src/manifest.json" not in script


def test_wechat_dev_script_cleans_and_validates_page_outputs() -> None:
    script = Path("scripts/wechat_miniprogram_dev.sh").read_text(encoding="utf-8")

    assert "clean_dev_output" in script
    assert "rm -rf \"$APP_DIR/dist/dev/mp-weixin\"" in script
    assert "check_page_outputs" in script
    assert "pages/index/index pages/profile/profile pages/login/login" in script
    assert "for ext in wxml js json wxss" in script


def test_wechat_build_script_reuses_dev_script_without_installing_dependencies() -> None:
    script = Path("scripts/wechat_miniprogram_build.sh").read_text(encoding="utf-8")

    assert "wechat_miniprogram_dev.sh" in script
    assert "build-local" in script
    assert "build" in script
    assert "\npnpm install" not in script
