; LifeOS 安装器（方案 4.1 阶段四）。Inno Setup 6 编译：
;   ISCC.exe tools\lifeos-setup.iss
; 前置：tools\build_exe.ps1 已跑完（dist\LifeOS\ 存在）。
; 数据目录 %USERPROFILE%\lifeOS 含用户记忆数据，卸载时询问、默认保留。

#define MyAppName "LifeOS"
#define MyAppVersion "2.2.1"
#define MyAppExeName "LifeOS.exe"
#define MyAppDataName "lifeOS"

[Setup]
AppId={{8A6C2F10-4E2B-4A9B-9C3D-LIFEOS0000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=LifeOS
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=LifeOS-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
; 安装包（Setup.exe）自身及其在“添加删除程序”里的图标
SetupIconFile=assets\lifeos.ico

[Languages]
; 简体中文语言文件随仓库放在 tools\Languages（静默安装的 Inno Setup 不带非默认语言），
; 用 {#SourcePath} 指向本 .iss 所在目录，避免依赖编译时的工作目录与编译器安装语言。
Name: "chinesesimplified"; MessagesFile: "{#SourcePath}\Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式(&D)"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "..\dist\LifeOS\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs replacesameversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{%USERPROFILE}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{%USERPROFILE}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{%USERPROFILE}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 只清安装目录内的运行残留；数据目录在 [Code] 里询问后处理。

[Code]
const
  DataSubKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppName}_is1';

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{%USERPROFILE}\{#MyAppDataName}');
    if DirExists(DataDir) then
      if MsgBox('是否同时删除用户数据目录？' #13#10 +
                DataDir + #13#10 #13#10 +
                '其中包含记忆、账户与日志。删除后无法恢复。',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
