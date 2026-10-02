# create_vm.ps1 - make the Prevue test VM in VirtualBox (Windows host).
#
# Debian 13 netinst, unattended install, bridged onto the wired LAN so the VM's
# multicast reaches the XTV125D. Run in a normal PowerShell window (no admin needed):
#
#   powershell -ExecutionPolicy Bypass -File tools\prevue-vm\create_vm.ps1 -Iso C:\ISOs\debian-13.x.x-amd64-netinst.iso
#
# Options: -Name, -Cpus, -MemoryMB, -DiskGB, -Adapter "<exact host adapter name>", -User, -Password
# Afterwards: docs/prevue-vm.md, step 3.
param(
    [Parameter(Mandatory = $true)][string]$Iso,
    [string]$Name = "bakacast-prevue",
    [int]$Cpus = 4,
    [int]$MemoryMB = 4096,
    [int]$DiskGB = 20,
    [string]$Adapter = "",
    [string]$User = "bakacast",
    [string]$Password = "bakacast"
)
$ErrorActionPreference = "Stop"

$vbm = Join-Path $env:ProgramFiles "Oracle\VirtualBox\VBoxManage.exe"
if (-not (Test-Path $vbm)) { throw "VBoxManage.exe not found at $vbm - install VirtualBox 7.1 or later." }
if (-not (Test-Path $Iso)) { throw "ISO not found: $Iso" }
& $vbm --version

# Pick the bridge adapter: the wired NIC that carries the default route.
# Wi-Fi bridging rewrites MACs and multicast is unreliable over it - use Ethernet.
if (-not $Adapter) {
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Sort-Object RouteMetric | Select-Object -First 1
    $Adapter = (Get-NetAdapter -InterfaceIndex $route.InterfaceIndex).InterfaceDescription
}
Write-Host "Bridging onto: $Adapter"
$bridged = (& $vbm list bridgedifs) -match "^Name:\s+(.*)$" | ForEach-Object { ($_ -replace "^Name:\s+", "").Trim() }
if ($bridged -notcontains $Adapter) {
    Write-Host "VirtualBox's bridgeable adapters:"; $bridged | ForEach-Object { Write-Host "  $_" }
    throw "'$Adapter' isn't one of them. Re-run with -Adapter `"<one of the names above>`"."
}

$vmDir = Join-Path $env:USERPROFILE "VirtualBox VMs\$Name"
$disk = Join-Path $vmDir "$Name.vdi"

& $vbm createvm --name $Name --ostype Debian_64 --register
& $vbm modifyvm $Name --cpus $Cpus --memory $MemoryMB --vram 16 --graphicscontroller vmsvga `
    --firmware bios --rtc-use-utc on --audio-driver none `
    --nic1 bridged --bridge-adapter1 "$Adapter" --nic-type1 virtio --cable-connected1 on `
    --nic-promisc1 allow-all
& $vbm createmedium disk --filename $disk --size ($DiskGB * 1024) --format VDI
& $vbm storagectl $Name --name SATA --add sata --controller IntelAhci --portcount 2
& $vbm storageattach $Name --storagectl SATA --port 0 --device 0 --type hdd --medium $disk
& $vbm storageattach $Name --storagectl SATA --port 1 --device 0 --type dvddrive --medium emptydrive

# Unattended Debian install (VirtualBox 7.1+). If this step errors, install by hand instead:
# attach the ISO, boot, and in tasksel pick ONLY "SSH server" + "standard system utilities".
& $vbm unattended install $Name --iso="$Iso" --user=$User --password=$Password `
    --full-user-name="Bakacast" --hostname="$Name.local" --time-zone="America/New_York" `
    --locale=en_US --country=US --package-selection-adjustment=minimal --start-vm=gui

Write-Host ""
Write-Host "Installing. When the VM reboots to a login prompt, log in as $User / $Password and"
Write-Host "follow docs/prevue-vm.md step 3 (find its IP with:  ip -4 addr show)."
