; UTF-8. Build-time paths are supplied by scripts/build_windows.py.
[Setup]
AppId={{455C23B2-9D6D-45B5-B8CD-F1DD281F7465}
AppName=ZJU-AC
AppVersion={#AppVersion}
DefaultDirName={src}\ZJU-AC
DefaultGroupName=ZJU-AC
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern dark
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\ZJU-AC.exe
OutputDir={#OutputDir}
OutputBaseFilename=ZJU-AC-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\ZJU-AC"; Filename: "{app}\ZJU-AC.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ZJU-AC"; Filename: "{app}\ZJU-AC.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ZJU-AC.exe"; Description: "Launch ZJU-AC"; Flags: nowait postinstall skipifsilent
