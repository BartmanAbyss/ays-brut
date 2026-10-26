<#
  Set every active display to a refresh rate, keeping its current resolution.

      .\Set-RefreshRate.ps1 60
      .\Set-RefreshRate.ps1 165
      .\Set-RefreshRate.ps1 -List        # offered rates, no change
      .\Set-RefreshRate.ps1 -Exact       # true rates, no change

  One QueryDisplayConfig, one SetDisplayConfig, every display at once.

  Why not ChangeDisplaySettingsEx: DEVMODE carries the rate as an INT, and this
  panel offers 59.95 and 59.9988 as separate modes that differ in nothing else.
  The legacy closest-match rounds both to 60 and picks the first, so asking for
  60 silently gives you 59.95 - and still returns DISP_CHANGE_SUCCESSFUL.
  DISPLAYCONFIG_RATIONAL says 60000/1000 and gets the real one.

  Desktop rate and signal rate are different things, and Settings shows both.
  With VRR on, a 60 Hz desktop may be carried on a 120 Hz signal (frame
  doubling), so the signal is not a read-back of what you asked for.

  Windows PowerShell 5.1, no admin needed.
#>
[CmdletBinding(DefaultParameterSetName = 'Set')]
param(
  [Parameter(ParameterSetName = 'Set', Position = 0, Mandatory = $true)]
  [double]$Hz,

  [Parameter(ParameterSetName = 'List')]  [switch]$List,
  [Parameter(ParameterSetName = 'Exact')] [switch]$Exact
)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
public struct LUID { public uint LowPart; public int HighPart; }

[StructLayout(LayoutKind.Sequential)]
public struct DC_RATIONAL { public uint Numerator; public uint Denominator; }

[StructLayout(LayoutKind.Sequential)]
public struct DC_PATH_SOURCE_INFO {
  public LUID adapterId;
  public uint id;
  public uint modeInfoIdx;
  public uint statusFlags;   // easy to miss; without it PATH_INFO is 68, not 72,
}                            // and every field past sourceInfo reads shifted.

[StructLayout(LayoutKind.Sequential)]
public struct DC_PATH_TARGET_INFO {
  public LUID adapterId;
  public uint id;
  public uint modeInfoIdx;
  public uint outputTechnology;
  public uint rotation;
  public uint scaling;
  public DC_RATIONAL refreshRate;
  public uint scanLineOrdering;
  public int  targetAvailable;
  public uint statusFlags;
}

[StructLayout(LayoutKind.Sequential)]
public struct DC_PATH_INFO {
  public DC_PATH_SOURCE_INFO sourceInfo;
  public DC_PATH_TARGET_INFO targetInfo;
  public uint flags;
}

[StructLayout(LayoutKind.Sequential)]
public struct DC_2DREGION { public uint cx; public uint cy; }

[StructLayout(LayoutKind.Sequential)]
public struct DC_VIDEO_SIGNAL_INFO {
  public ulong pixelRate;
  public DC_RATIONAL hSyncFreq;
  public DC_RATIONAL vSyncFreq;
  public DC_2DREGION activeSize;
  public DC_2DREGION totalSize;
  public uint videoStandard;
  public uint scanLineOrdering;
}

[StructLayout(LayoutKind.Sequential)]
public struct DC_TARGET_MODE { public DC_VIDEO_SIGNAL_INFO targetVideoSignalInfo; }

[StructLayout(LayoutKind.Sequential)]
public struct DC_SOURCE_MODE {
  public uint width; public uint height; public uint pixelFormat;
  public int positionX; public int positionY;
}

[StructLayout(LayoutKind.Explicit)]
public struct DC_MODE_INFO {
  [FieldOffset(0)]  public uint infoType;
  [FieldOffset(4)]  public uint id;
  [FieldOffset(8)]  public LUID adapterId;
  [FieldOffset(16)] public DC_TARGET_MODE targetMode;
  [FieldOffset(16)] public DC_SOURCE_MODE sourceMode;
}

[StructLayout(LayoutKind.Sequential)]
public struct DC_DEVICE_INFO_HEADER {
  public uint type; public uint size; public LUID adapterId; public uint id;
}

[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct DC_SOURCE_DEVICE_NAME {
  public DC_DEVICE_INFO_HEADER header;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string viewGdiDeviceName;
}

// Only for reporting: the DESKTOP rate and the list of offered rates have no
// CCD equivalent, so they still come from the old enumeration.
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
public struct DEVMODE {
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
  public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra;
  public int dmFields;
  public int dmPositionX, dmPositionY, dmDisplayOrientation, dmDisplayFixedOutput;
  public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
  [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
  public short dmLogPixels;
  public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
  public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight;
}

public static class Disp {
  [DllImport("user32.dll")]
  public static extern int GetDisplayConfigBufferSizes(uint flags, out uint numPath, out uint numMode);

  [DllImport("user32.dll")]
  public static extern int QueryDisplayConfig(uint flags, ref uint numPath, [Out] DC_PATH_INFO[] paths,
                                              ref uint numMode, [Out] DC_MODE_INFO[] modes, IntPtr topologyId);

  [DllImport("user32.dll")]
  public static extern int SetDisplayConfig(uint numPath, [In] DC_PATH_INFO[] paths,
                                            uint numMode, [In] DC_MODE_INFO[] modes, uint flags);

  [DllImport("user32.dll")]
  public static extern int DisplayConfigGetDeviceInfo(ref DC_SOURCE_DEVICE_NAME packet);

  [DllImport("user32.dll", CharSet = CharSet.Ansi)]
  public static extern bool EnumDisplaySettings(string device, int modeNum, ref DEVMODE dm);
}
'@

$QDC_ONLY_ACTIVE_PATHS = 2
$ENUM_CURRENT          = -1

# SDC_USE_SUPPLIED_DISPLAY_CONFIG 0x20 | SDC_APPLY 0x80
#   | SDC_SAVE_TO_DATABASE 0x200 | SDC_ALLOW_CHANGES 0x400
$SDC_APPLY_CFG = 0x20 -bor 0x80 -bor 0x200 -bor 0x400

function New-DevMode {
  $dm = New-Object DEVMODE
  # [int16], not [short]: PowerShell 5.1 has no [short] accelerator.
  $dm.dmSize = [int16][System.Runtime.InteropServices.Marshal]::SizeOf([type]'DEVMODE')
  return $dm
}

function Get-Config {
  $np = 0; $nm = 0
  if ([Disp]::GetDisplayConfigBufferSizes($QDC_ONLY_ACTIVE_PATHS, [ref]$np, [ref]$nm) -ne 0) {
    throw 'GetDisplayConfigBufferSizes failed'
  }
  $paths = New-Object 'DC_PATH_INFO[]' $np
  $modes = New-Object 'DC_MODE_INFO[]' $nm
  if ([Disp]::QueryDisplayConfig($QDC_ONLY_ACTIVE_PATHS, [ref]$np, $paths, [ref]$nm, $modes, [IntPtr]::Zero) -ne 0) {
    throw 'QueryDisplayConfig failed'
  }
  @{ np = $np; nm = $nm; paths = $paths; modes = $modes }
}

function Get-GdiName {
  param($SourceInfo)
  # Build the header whole. $pkt.header.type = 1 writes into a COPY of the
  # nested struct and is silently discarded, leaving the packet zeroed.
  $h = New-Object DC_DEVICE_INFO_HEADER
  $h.type = 1   # DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
  $h.size = [System.Runtime.InteropServices.Marshal]::SizeOf([type]'DC_SOURCE_DEVICE_NAME')
  $h.adapterId = $SourceInfo.adapterId
  $h.id = $SourceInfo.id
  $pkt = New-Object DC_SOURCE_DEVICE_NAME
  $pkt.header = $h
  if ([Disp]::DisplayConfigGetDeviceInfo([ref]$pkt) -eq 0) { $pkt.viewGdiDeviceName } else { $null }
}

function Show-Status {
  param($Cfg, [switch]$WithRates)
  for ($i = 0; $i -lt $Cfg.np; $i++) {
    $p = $Cfg.paths[$i]
    $who = Get-GdiName $p.sourceInfo
    if (-not $who) { continue }

    $cur = New-DevMode
    [void][Disp]::EnumDisplaySettings($who, $ENUM_CURRENT, [ref]$cur)

    $idx = $p.targetInfo.modeInfoIdx
    $sig = ''
    if ($idx -lt $Cfg.nm) {
      $v = $Cfg.modes[$idx].targetMode.targetVideoSignalInfo
      if ($v.totalSize.cx -gt 0 -and $v.totalSize.cy -gt 0) {
        $sig = ', signal {0:N4} Hz ({1:N0} Hz pixel clock / {2}x{3} raster)' -f
               ($v.pixelRate / ([double]$v.totalSize.cx * $v.totalSize.cy)), $v.pixelRate, $v.totalSize.cx, $v.totalSize.cy
      }
    }
    Write-Host ("  {0} : {1}x{2} desktop {3} Hz{4}" -f $who, $cur.dmPelsWidth, $cur.dmPelsHeight, $cur.dmDisplayFrequency, $sig)

    if ($WithRates) {
      $rates = @(); $m = 0
      while ($true) {
        $d = New-DevMode
        if (-not [Disp]::EnumDisplaySettings($who, $m, [ref]$d)) { break }
        if ($d.dmPelsWidth -eq $cur.dmPelsWidth -and $d.dmPelsHeight -eq $cur.dmPelsHeight -and
            $d.dmBitsPerPel -eq $cur.dmBitsPerPel) { $rates += $d.dmDisplayFrequency }
        $m++
      }
      Write-Host ("      offered: {0}" -f (($rates | Sort-Object -Unique) -join ', '))
    }
  }
}

$cfg = Get-Config
if ($cfg.np -eq 0) { Write-Warning 'No active displays.'; return }

if ($List)  { Show-Status $cfg -WithRates; return }
if ($Exact) { Show-Status $cfg; return }

# Name the rate as a rational on every path, and let the OS resolve the timing.
$rat = New-Object DC_RATIONAL
$rat.Numerator   = [uint32][math]::Round($Hz * 1000)
$rat.Denominator = 1000

for ($i = 0; $i -lt $cfg.np; $i++) {
  # Read-modify-write the WHOLE element: indexing an array of structs hands you
  # a copy, so $cfg.paths[$i].targetInfo.refreshRate = $rat is discarded.
  $p = $cfg.paths[$i]
  $t = $p.targetInfo
  $t.refreshRate = $rat
  # DISPLAYCONFIG_PATH_MODE_IDX_INVALID. [uint32]::MaxValue, not 0xFFFFFFFF -
  # PowerShell 5.1 parses that literal as Int32 -1, which will not assign.
  $t.modeInfoIdx = [uint32]::MaxValue
  $p.targetInfo = $t
  $cfg.paths[$i] = $p
}

$r = [Disp]::SetDisplayConfig($cfg.np, $cfg.paths, $cfg.nm, $cfg.modes, $SDC_APPLY_CFG)
if ($r -ne 0) {
  Write-Warning "SetDisplayConfig failed for $Hz Hz (error $r) - nothing changed."
  return
}

Write-Host "$Hz Hz applied:"
Show-Status (Get-Config)
