; Compile with: ISCC /DAppVersion=1.2.0 /DPayloadDir=... /DReleaseDir=... build_windows.iss
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif
[Setup]
AppId={{B60DA9F6-D430-47DB-AE3D-F73E4280B53F}
AppName=神录剪
AppVersion={#AppVersion}
AppPublisher=神录剪
DefaultDirName={localappdata}\Programs\Shenlujian
DefaultGroupName=神录剪
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#ReleaseDir}
OutputBaseFilename=shenlujian-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\shenlujian.exe
LicenseFile={#PayloadDir}\LICENSE
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked
[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\神录剪"; Filename: "{app}\shenlujian.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\神录剪"; Filename: "{app}\shenlujian.exe"; WorkingDir: "{app}"; Tasks: desktopicon
[Run]
Filename: "{app}\shenlujian.exe"; Description: "启动神录剪"; Flags: nowait postinstall skipifsilent
