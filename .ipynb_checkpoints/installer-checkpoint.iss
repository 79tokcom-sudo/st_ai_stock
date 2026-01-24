#define MyAppName "STAI ONEUI"
#define MyAppVersion "1.0.0"
#define MyAppExeName "STAI_ONEUI.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=installer_output
OutputBaseFilename=STAI_ONEUI_Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Firebase 키 파일을 설치 폴더에 같이 넣고 싶으면 아래 줄 사용(보안주의)
Source: "staidb-firebase-adminsdk-fbsvc-d3ba815ea4.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "프로그램 실행"; Flags: nowait postinstall skipifsilent
