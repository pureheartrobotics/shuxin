# Elevate: bind KickPi ADB WinUSB interface GUID and restart the USB node.
$ErrorActionPreference = "Continue"
$id = "USB\VID_2207&PID_0006\66C78D9A67689F0E"
$guid = "{F72FE0D4-CBCB-407D-8814-9ED673D0DD6B}"
$reg = "HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_2207&PID_0006\66C78D9A67689F0E\Device Parameters"

New-Item -Path $reg -Force | Out-Null
New-ItemProperty -Path $reg -Name "DeviceInterfaceGUIDs" -PropertyType MultiString -Value $guid -Force | Out-Null
Write-Host "set DeviceInterfaceGUIDs $guid"

pnputil /restart-device $id
if ($LASTEXITCODE -ne 0) {
    Write-Host "restart-device failed ($LASTEXITCODE), try disable/enable"
    Disable-PnpDevice -InstanceId $id -Confirm:$false -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Enable-PnpDevice -InstanceId $id -Confirm:$false -ErrorAction SilentlyContinue
}
Write-Host "usb node reset done"
Get-PnpDevice -InstanceId $id | Format-List Status, FriendlyName, Class
