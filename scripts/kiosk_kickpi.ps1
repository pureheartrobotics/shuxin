# Make 初心 the device: install, grant mic/camera, set HOME, try device-owner lock-task.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AdbCandidates = @(
    (Join-Path $Root "RKDevTool_v3.30_for_window\RKDevTool_v3.30_for_window\bin\adb.exe"),
    (Join-Path $Root ".android-sdk\platform-tools\adb.exe")
)
$Adb = $AdbCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Adb) { throw "adb not found" }

$Apk = Join-Path $Root "android-app\app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $Apk)) { throw "APK missing. Build android-app first." }

function Invoke-Adb {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & $Adb @Args
}

Write-Host "install $Apk"
Invoke-Adb install -r -g $Apk
Invoke-Adb shell pm grant cn.shuxin.car android.permission.RECORD_AUDIO
Invoke-Adb shell pm grant cn.shuxin.car android.permission.CAMERA
Invoke-Adb shell cmd package set-home-activity cn.shuxin.car/.MainActivity
Invoke-Adb shell cmd role add-role-holder android.app.role.HOME cn.shuxin.car 2>$null
$owner = Invoke-Adb shell dpm set-device-owner cn.shuxin.car/.KioskAdminReceiver 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $owner -match "Error|already") {
    Write-Host "device-owner not set (normal if the board already has a user). HOME + grants still applied."
    Write-Host $owner.Trim()
} else {
    Write-Host "device-owner set; lock-task and HOME will survive reboot."
}
Invoke-Adb shell am start -n cn.shuxin.car/.MainActivity
Write-Host "reboot to confirm the face, not the Android launcher"
Invoke-Adb reboot
