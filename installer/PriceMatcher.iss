; ============================================================
;  PriceMatcher - Windows installer (Inno Setup 6)
;  Build:  installer\build_installer.bat
;  Result: installer\output\PriceMatcher-Setup.exe
;
;  Per-user install (no admin rights needed) into
;  %LOCALAPPDATA%\Programs\PriceMatcher so that config.json and
;  logs\ stay writable - unlike Program Files.
; ============================================================

#define AppName      "Price Matcher"
#define AppVersion   "1.0.0"
#define AppPublisher "Your Company"
#define AppExe       "PriceMatcher.exe"

[Setup]
AppId={{8D2A5F31-4C77-4E1B-9A0E-5C1B7E2F9A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\PriceMatcher
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=PriceMatcher-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
; Persian is not shipped with Inno Setup by default. If you download
; Persian.isl into Inno Setup's Languages folder, uncomment the next line:
; Name: "fa"; MessagesFile: "compiler:Languages\Persian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "installocr"; Description: "نصب موتور OCR (Tesseract) - فقط برای PDF های اسکن‌شده لازم است"; \
    GroupDescription: "امکانات اختیاری:"; Flags: unchecked; \
    Check: FileExists(ExpandConstant('{src}\deps\tesseract-ocr-setup.exe'))

[Files]
; --- the whole PyInstaller onedir output ---
Source: "..\dist\PriceMatcher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; --- config.json must survive an upgrade: never overwrite the user's copy ---
Source: "..\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
; --- WebView2 runtime bootstrapper: optional. Download once from
;     https://developer.microsoft.com/microsoft-edge/webview2/ (the small
;     "Evergreen Bootstrapper", ~2 MB) and place it at installer\deps\.
;     The installer compiles fine even if this file is absent. ---
Source: "deps\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; \
    Flags: deleteafterinstall skipifsourcedoesntexist; Check: NeedsWebView2
; --- optional Tesseract OCR installer. Download once from
;     https://github.com/UB-Mannheim/tesseract/wiki and place it at
;     installer\deps\tesseract-ocr-setup.exe. Only copied/run if the user
;     ticks the box above; safely skipped if the file is not there. ---
Source: "deps\tesseract-ocr-setup.exe"; DestDir: "{tmp}"; \
    Flags: deleteafterinstall skipifsourcedoesntexist; Tasks: installocr

[Dirs]
Name: "{app}\logs"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; install the WebView2 runtime silently, only when it is missing
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; \
    StatusMsg: "در حال نصب Microsoft Edge WebView2 Runtime..."; Check: NeedsWebView2; \
    Flags: waituntilterminated skipifdoesntexist
; Tesseract's official installer supports a silent /S flag (NSIS-based)
Filename: "{tmp}\tesseract-ocr-setup.exe"; Parameters: "/S"; \
    StatusMsg: "در حال نصب موتور OCR..."; Tasks: installocr; \
    Flags: waituntilterminated skipifdoesntexist
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"

[Code]
{ WebView2 registers its version under these keys when present. }
function NeedsWebView2: Boolean;
var
  Version: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
    if (Version <> '') and (Version <> '0.0.0.0') then
      Result := False;
  if Result then
    if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) then
      if (Version <> '') and (Version <> '0.0.0.0') then
        Result := False;
end;
