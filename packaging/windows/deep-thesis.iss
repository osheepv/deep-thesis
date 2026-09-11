#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0-beta.1"
#endif

[Setup]
AppId={{98B6B932-2B2F-4D98-9EC7-59FE0031CDA1}
AppName=Deep Thesis
AppVersion={#AppVersion}
AppPublisher=Deep Thesis contributors
AppPublisherURL=https://github.com/osheepv/deep-thesis
DefaultDirName={localappdata}\Programs\Deep Thesis
DefaultGroupName=Deep Thesis
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=DeepThesis-{#AppVersion}-windows-x64-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\DeepThesis.exe
AppMutex=Local\DeepThesis.Desktop
CloseApplications=no
LicenseFile={#BundleDir}\app\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Deep Thesis"; Filename: "{app}\DeepThesis.exe"
Name: "{autodesktop}\Deep Thesis"; Filename: "{app}\DeepThesis.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DeepThesis.exe"; Description: "Open Deep Thesis"; Flags: nowait postinstall skipifsilent

; User papers and logs live outside {app}. Uninstall never deletes them.
